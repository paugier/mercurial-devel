// filepatterns.rs
//
// Copyright 2019 Raphaël Gomès <rgomes@octobus.net>
//
// This software may be used and distributed according to the terms of the
// GNU General Public License version 2 or any later version.

//! Handling of Mercurial-specific patterns.

use crate::{
    utils::{
        files::{canonical_path, get_bytes_from_path, get_path_from_bytes},
        hg_path::{path_to_hg_path_buf, HgPathBuf, HgPathError},
        SliceExt,
    },
    FastHashMap, PatternError,
};
use lazy_static::lazy_static;
use regex::bytes::{NoExpand, Regex};
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::vec::Vec;

lazy_static! {
    static ref RE_ESCAPE: Vec<Vec<u8>> = {
        let mut v: Vec<Vec<u8>> = (0..=255).map(|byte| vec![byte]).collect();
        let to_escape = b"()[]{}?*+-|^$\\.&~#\t\n\r\x0b\x0c";
        for byte in to_escape {
            v[*byte as usize].insert(0, b'\\');
        }
        v
    };
}

/// These are matched in order
const GLOB_REPLACEMENTS: &[(&[u8], &[u8])] =
    &[(b"*/", b"(?:.*/)?"), (b"*", b".*"), (b"", b"[^/]*")];

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PatternSyntax {
    /// A regular expression
    Regexp,
    /// Glob that matches at the front of the path
    RootGlob,
    /// Glob that matches at any suffix of the path (still anchored at
    /// slashes)
    Glob,
    /// a path relative to repository root, which is matched recursively
    Path,
    /// a single exact path relative to repository root
    FilePath,
    /// A path relative to cwd
    RelPath,
    /// an unrooted glob (*.rs matches Rust files in all dirs)
    RelGlob,
    /// A regexp that needn't match the start of a name
    RelRegexp,
    /// A path relative to repository root, which is matched non-recursively
    /// (will not match subdirectories)
    RootFiles,
    /// A file of patterns to read and include
    Include,
    /// A file of patterns to match against files under the same directory
    SubInclude,
    /// SubInclude with the result of parsing the included file
    ///
    /// Note: there is no ExpandedInclude because that expansion can be done
    /// in place by replacing the Include pattern by the included patterns.
    /// SubInclude requires more handling.
    ///
    /// Note: `Box` is used to minimize size impact on other enum variants
    ExpandedSubInclude(Box<SubInclude>),
}

/// Transforms a glob pattern into a regex
fn glob_to_re(pat: &[u8]) -> Vec<u8> {
    let mut input = pat;
    let mut res: Vec<u8> = vec![];
    let mut group_depth = 0;

    while let Some((c, rest)) = input.split_first() {
        input = rest;

        match c {
            b'*' => {
                for (source, repl) in GLOB_REPLACEMENTS {
                    if let Some(rest) = input.drop_prefix(source) {
                        input = rest;
                        res.extend(*repl);
                        break;
                    }
                }
            }
            b'?' => res.extend(b"."),
            b'[' => {
                match input.iter().skip(1).position(|b| *b == b']') {
                    None => res.extend(b"\\["),
                    Some(end) => {
                        // Account for the one we skipped
                        let end = end + 1;

                        res.extend(b"[");

                        for (i, b) in input[..end].iter().enumerate() {
                            if *b == b'!' && i == 0 {
                                res.extend(b"^")
                            } else if *b == b'^' && i == 0 {
                                res.extend(b"\\^")
                            } else if *b == b'\\' {
                                res.extend(b"\\\\")
                            } else {
                                res.push(*b)
                            }
                        }
                        res.extend(b"]");
                        input = &input[end + 1..];
                    }
                }
            }
            b'{' => {
                group_depth += 1;
                res.extend(b"(?:")
            }
            b'}' if group_depth > 0 => {
                group_depth -= 1;
                res.extend(b")");
            }
            b',' if group_depth > 0 => res.extend(b"|"),
            b'\\' => {
                let c = {
                    if let Some((c, rest)) = input.split_first() {
                        input = rest;
                        c
                    } else {
                        c
                    }
                };
                res.extend(&RE_ESCAPE[*c as usize])
            }
            _ => res.extend(&RE_ESCAPE[*c as usize]),
        }
    }
    res
}

fn escape_pattern(pattern: &[u8]) -> Vec<u8> {
    pattern
        .iter()
        .flat_map(|c| RE_ESCAPE[*c as usize].clone())
        .collect()
}

pub fn parse_pattern_syntax(
    kind: &[u8],
) -> Result<PatternSyntax, PatternError> {
    match kind {
        b"re:" => Ok(PatternSyntax::Regexp),
        b"path:" => Ok(PatternSyntax::Path),
        b"filepath:" => Ok(PatternSyntax::FilePath),
        b"relpath:" => Ok(PatternSyntax::RelPath),
        b"rootfilesin:" => Ok(PatternSyntax::RootFiles),
        b"relglob:" => Ok(PatternSyntax::RelGlob),
        b"relre:" => Ok(PatternSyntax::RelRegexp),
        b"glob:" => Ok(PatternSyntax::Glob),
        b"rootglob:" => Ok(PatternSyntax::RootGlob),
        b"include:" => Ok(PatternSyntax::Include),
        b"subinclude:" => Ok(PatternSyntax::SubInclude),
        _ => Err(PatternError::UnsupportedSyntax(
            String::from_utf8_lossy(kind).to_string(),
        )),
    }
}

lazy_static! {
    static ref FLAG_RE: Regex = Regex::new(r"^\(\?[aiLmsux]+\)").unwrap();
}

/// Builds the regex that corresponds to the given pattern.
/// If within a `syntax: regexp` context, returns the pattern,
/// otherwise, returns the corresponding regex.
fn _build_single_regex(entry: &IgnorePattern, glob_suffix: &[u8]) -> Vec<u8> {
    let IgnorePattern {
        syntax, pattern, ..
    } = entry;
    if pattern.is_empty() {
        return vec![];
    }
    match syntax {
        PatternSyntax::Regexp => pattern.to_owned(),
        PatternSyntax::RelRegexp => {
            // The `regex` crate accepts `**` while `re2` and Python's `re`
            // do not. Checking for `*` correctly triggers the same error all
            // engines.
            if pattern[0] == b'^'
                || pattern[0] == b'*'
                || pattern.starts_with(b".*")
            {
                return pattern.to_owned();
            }
            match FLAG_RE.find(pattern) {
                Some(mat) => {
                    let s = mat.start();
                    let e = mat.end();
                    [
                        &b"(?"[..],
                        &pattern[s + 2..e - 1],
                        &b":"[..],
                        if pattern[e] == b'^'
                            || pattern[e] == b'*'
                            || pattern[e..].starts_with(b".*")
                        {
                            &b""[..]
                        } else {
                            &b".*"[..]
                        },
                        &pattern[e..],
                        &b")"[..],
                    ]
                    .concat()
                }
                None => [&b".*"[..], pattern].concat(),
            }
        }
        PatternSyntax::Path | PatternSyntax::RelPath => {
            if pattern == b"." {
                return vec![];
            }
            [escape_pattern(pattern).as_slice(), b"(?:/|$)"].concat()
        }
        PatternSyntax::RootFiles => {
            let mut res = if pattern == b"." {
                vec![]
            } else {
                // Pattern is a directory name.
                [escape_pattern(pattern).as_slice(), b"/"].concat()
            };

            // Anything after the pattern must be a non-directory.
            res.extend(b"[^/]+$");
            res
        }
        PatternSyntax::RelGlob => {
            let glob_re = glob_to_re(pattern);
            if let Some(rest) = glob_re.drop_prefix(b"[^/]*") {
                [b".*", rest, glob_suffix].concat()
            } else {
                [b"(?:.*/)?", glob_re.as_slice(), glob_suffix].concat()
            }
        }
        PatternSyntax::Glob | PatternSyntax::RootGlob => {
            [glob_to_re(pattern).as_slice(), glob_suffix].concat()
        }
        PatternSyntax::Include
        | PatternSyntax::SubInclude
        | PatternSyntax::ExpandedSubInclude(_)
        | PatternSyntax::FilePath => unreachable!(),
    }
}

const GLOB_SPECIAL_CHARACTERS: [u8; 7] =
    [b'*', b'?', b'[', b']', b'{', b'}', b'\\'];

/// TODO support other platforms
#[cfg(unix)]
pub fn normalize_path_bytes(bytes: &[u8]) -> Vec<u8> {
    if bytes.is_empty() {
        return b".".to_vec();
    }
    let sep = b'/';

    let mut initial_slashes = bytes.iter().take_while(|b| **b == sep).count();
    if initial_slashes > 2 {
        // POSIX allows one or two initial slashes, but treats three or more
        // as single slash.
        initial_slashes = 1;
    }
    let components = bytes
        .split(|b| *b == sep)
        .filter(|c| !(c.is_empty() || c == b"."))
        .fold(vec![], |mut acc, component| {
            if component != b".."
                || (initial_slashes == 0 && acc.is_empty())
                || (!acc.is_empty() && acc[acc.len() - 1] == b"..")
            {
                acc.push(component)
            } else if !acc.is_empty() {
                acc.pop();
            }
            acc
        });
    let mut new_bytes = components.join(&sep);

    if initial_slashes > 0 {
        let mut buf: Vec<_> = (0..initial_slashes).map(|_| sep).collect();
        buf.extend(new_bytes);
        new_bytes = buf;
    }
    if new_bytes.is_empty() {
        b".".to_vec()
    } else {
        new_bytes
    }
}

/// Wrapper function to `_build_single_regex` that short-circuits 'exact' globs
/// that don't need to be transformed into a regex.
pub fn build_single_regex(
    entry: &IgnorePattern,
    glob_suffix: &[u8],
) -> Result<Option<Vec<u8>>, PatternError> {
    let IgnorePattern {
        pattern, syntax, ..
    } = entry;
    let pattern = match syntax {
        PatternSyntax::RootGlob
        | PatternSyntax::Path
        | PatternSyntax::RelGlob
        | PatternSyntax::RelPath
        | PatternSyntax::RootFiles => normalize_path_bytes(pattern),
        PatternSyntax::Include | PatternSyntax::SubInclude => {
            return Err(PatternError::NonRegexPattern(entry.clone()))
        }
        _ => pattern.to_owned(),
    };
    let is_simple_rootglob = *syntax == PatternSyntax::RootGlob
        && !pattern.iter().any(|b| GLOB_SPECIAL_CHARACTERS.contains(b));
    if is_simple_rootglob || syntax == &PatternSyntax::FilePath {
        Ok(None)
    } else {
        let mut entry = entry.clone();
        entry.pattern = pattern;
        Ok(Some(_build_single_regex(&entry, glob_suffix)))
    }
}

lazy_static! {
    static ref SYNTAXES: FastHashMap<&'static [u8], PatternSyntax> = {
        let mut m = FastHashMap::default();

        m.insert(b"re:".as_ref(), PatternSyntax::Regexp);
        m.insert(b"regexp:".as_ref(), PatternSyntax::Regexp);
        m.insert(b"path:".as_ref(), PatternSyntax::Path);
        m.insert(b"filepath:".as_ref(), PatternSyntax::FilePath);
        m.insert(b"relpath:".as_ref(), PatternSyntax::RelPath);
        m.insert(b"rootfilesin:".as_ref(), PatternSyntax::RootFiles);
        m.insert(b"relglob:".as_ref(), PatternSyntax::RelGlob);
        m.insert(b"relre:".as_ref(), PatternSyntax::RelRegexp);
        m.insert(b"glob:".as_ref(), PatternSyntax::Glob);
        m.insert(b"rootglob:".as_ref(), PatternSyntax::RootGlob);
        m.insert(b"include:".as_ref(), PatternSyntax::Include);
        m.insert(b"subinclude:".as_ref(), PatternSyntax::SubInclude);

        m
    };
}

#[derive(Debug)]
pub enum PatternFileWarning {
    /// (file path, syntax bytes)
    InvalidSyntax(PathBuf, Vec<u8>),
    /// File path
    NoSuchFile(PathBuf),
}

pub fn parse_one_pattern(
    pattern: &[u8],
    source: &Path,
    default: PatternSyntax,
    normalize: bool,
) -> IgnorePattern {
    let mut pattern_bytes: &[u8] = pattern;
    let mut syntax = default;

    for (s, val) in SYNTAXES.iter() {
        if let Some(rest) = pattern_bytes.drop_prefix(s) {
            syntax = val.clone();
            pattern_bytes = rest;
            break;
        }
    }

    let pattern = match syntax {
        PatternSyntax::RootGlob
        | PatternSyntax::Path
        | PatternSyntax::Glob
        | PatternSyntax::RelGlob
        | PatternSyntax::RelPath
        | PatternSyntax::RootFiles
            if normalize =>
        {
            normalize_path_bytes(pattern_bytes)
        }
        _ => pattern_bytes.to_vec(),
    };

    IgnorePattern {
        syntax,
        pattern,
        source: source.to_owned(),
    }
}

pub fn parse_pattern_file_contents(
    lines: &[u8],
    file_path: &Path,
    default_syntax_override: Option<PatternSyntax>,
    warn: bool,
    relativize: bool,
) -> Result<(Vec<IgnorePattern>, Vec<PatternFileWarning>), PatternError> {
    let comment_regex = Regex::new(r"((?:^|[^\\])(?:\\\\)*)#.*").unwrap();

    #[allow(clippy::trivial_regex)]
    let comment_escape_regex = Regex::new(r"\\#").unwrap();
    let mut inputs: Vec<IgnorePattern> = vec![];
    let mut warnings: Vec<PatternFileWarning> = vec![];

    let mut current_syntax =
        default_syntax_override.unwrap_or(PatternSyntax::RelRegexp);

    for mut line in lines.split(|c| *c == b'\n') {
        let line_buf;
        if line.contains(&b'#') {
            if let Some(cap) = comment_regex.captures(line) {
                line = &line[..cap.get(1).unwrap().end()]
            }
            line_buf = comment_escape_regex.replace_all(line, NoExpand(b"#"));
            line = &line_buf;
        }

        let line = line.trim_end();

        if line.is_empty() {
            continue;
        }

        if let Some(syntax) = line.drop_prefix(b"syntax:") {
            let syntax = syntax.trim();

            if let Some(parsed) =
                SYNTAXES.get([syntax, &b":"[..]].concat().as_slice())
            {
                current_syntax = parsed.clone();
            } else if warn {
                warnings.push(PatternFileWarning::InvalidSyntax(
                    file_path.to_owned(),
                    syntax.to_owned(),
                ));
            }
        } else {
            let pattern = parse_one_pattern(
                line,
                file_path,
                current_syntax.clone(),
                false,
            );
            inputs.push(if relativize {
                pattern.to_relative()
            } else {
                pattern
            })
        }
    }
    Ok((inputs, warnings))
}

pub fn parse_pattern_args(
    patterns: Vec<Vec<u8>>,
    cwd: &Path,
    root: &Path,
) -> Result<Vec<IgnorePattern>, HgPathError> {
    let mut ignore_patterns: Vec<IgnorePattern> = Vec::new();
    for pattern in patterns {
        let pattern = parse_one_pattern(
            &pattern,
            Path::new("<args>"),
            PatternSyntax::RelPath,
            true,
        );
        match pattern.syntax {
            PatternSyntax::RelGlob | PatternSyntax::RelPath => {
                let name = get_path_from_bytes(&pattern.pattern);
                let canon = canonical_path(root, cwd, name)?;
                ignore_patterns.push(IgnorePattern {
                    syntax: pattern.syntax,
                    pattern: get_bytes_from_path(canon),
                    source: pattern.source,
                })
            }
            _ => ignore_patterns.push(pattern.to_owned()),
        };
    }
    Ok(ignore_patterns)
}

pub fn read_pattern_file(
    file_path: &Path,
    warn: bool,
    inspect_pattern_bytes: &mut impl FnMut(&Path, &[u8]),
) -> Result<(Vec<IgnorePattern>, Vec<PatternFileWarning>), PatternError> {
    match std::fs::read(file_path) {
        Ok(contents) => {
            inspect_pattern_bytes(file_path, &contents);
            parse_pattern_file_contents(&contents, file_path, None, warn, true)
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok((
            vec![],
            vec![PatternFileWarning::NoSuchFile(file_path.to_owned())],
        )),
        Err(e) => Err(e.into()),
    }
}

/// Represents an entry in an "ignore" file.
#[derive(Debug, Eq, PartialEq, Clone)]
pub struct IgnorePattern {
    pub syntax: PatternSyntax,
    pub pattern: Vec<u8>,
    pub source: PathBuf,
}

impl IgnorePattern {
    pub fn new(syntax: PatternSyntax, pattern: &[u8], source: &Path) -> Self {
        Self {
            syntax,
            pattern: pattern.to_owned(),
            source: source.to_owned(),
        }
    }

    pub fn to_relative(self) -> Self {
        let Self {
            syntax,
            pattern,
            source,
        } = self;
        Self {
            syntax: match syntax {
                PatternSyntax::Regexp => PatternSyntax::RelRegexp,
                PatternSyntax::Glob => PatternSyntax::RelGlob,
                x => x,
            },
            pattern,
            source,
        }
    }
}

pub type PatternResult<T> = Result<T, PatternError>;

/// Wrapper for `read_pattern_file` that also recursively expands `include:`
/// and `subinclude:` patterns.
///
/// The former are expanded in place, while `PatternSyntax::ExpandedSubInclude`
/// is used for the latter to form a tree of patterns.
pub fn get_patterns_from_file(
    pattern_file: &Path,
    root_dir: &Path,
    inspect_pattern_bytes: &mut impl FnMut(&Path, &[u8]),
) -> PatternResult<(Vec<IgnorePattern>, Vec<PatternFileWarning>)> {
    let (patterns, mut warnings) =
        read_pattern_file(pattern_file, true, inspect_pattern_bytes)?;
    let patterns = patterns
        .into_iter()
        .flat_map(|entry| -> PatternResult<_> {
            Ok(match &entry.syntax {
                PatternSyntax::Include => {
                    let inner_include =
                        root_dir.join(get_path_from_bytes(&entry.pattern));
                    let (inner_pats, inner_warnings) = get_patterns_from_file(
                        &inner_include,
                        root_dir,
                        inspect_pattern_bytes,
                    )?;
                    warnings.extend(inner_warnings);
                    inner_pats
                }
                PatternSyntax::SubInclude => {
                    let mut sub_include = SubInclude::new(
                        root_dir,
                        &entry.pattern,
                        &entry.source,
                    )?;
                    let (inner_patterns, inner_warnings) =
                        get_patterns_from_file(
                            &sub_include.path,
                            &sub_include.root,
                            inspect_pattern_bytes,
                        )?;
                    sub_include.included_patterns = inner_patterns;
                    warnings.extend(inner_warnings);
                    vec![IgnorePattern {
                        syntax: PatternSyntax::ExpandedSubInclude(Box::new(
                            sub_include,
                        )),
                        ..entry
                    }]
                }
                _ => vec![entry],
            })
        })
        .flatten()
        .collect();

    Ok((patterns, warnings))
}

/// Holds all the information needed to handle a `subinclude:` pattern.
#[derive(Debug, PartialEq, Eq, Clone)]
pub struct SubInclude {
    /// Will be used for repository (hg) paths that start with this prefix.
    /// It is relative to the current working directory, so comparing against
    /// repository paths is painless.
    pub prefix: HgPathBuf,
    /// The file itself, containing the patterns
    pub path: PathBuf,
    /// Folder in the filesystem where this it applies
    pub root: PathBuf,

    pub included_patterns: Vec<IgnorePattern>,
}

impl SubInclude {
    pub fn new(
        root_dir: &Path,
        pattern: &[u8],
        source: &Path,
    ) -> Result<SubInclude, HgPathError> {
        let normalized_source =
            normalize_path_bytes(&get_bytes_from_path(source));

        let source_root = get_path_from_bytes(&normalized_source);
        let source_root = source_root.parent().unwrap_or(source_root);

        let path = source_root.join(get_path_from_bytes(pattern));
        let new_root = path.parent().unwrap_or_else(|| path.deref());

        let prefix = canonical_path(root_dir, root_dir, new_root)?;

        Ok(Self {
            prefix: path_to_hg_path_buf(prefix).map(|mut p| {
                if !p.is_empty() {
                    p.push_byte(b'/');
                }
                p
            })?,
            path: path.to_owned(),
            root: new_root.to_owned(),
            included_patterns: Vec::new(),
        })
    }
}

/// Separate and pre-process subincludes from other patterns for the "ignore"
/// phase.
pub fn filter_subincludes(
    ignore_patterns: Vec<IgnorePattern>,
) -> Result<(Vec<SubInclude>, Vec<IgnorePattern>), HgPathError> {
    let mut subincludes = vec![];
    let mut others = vec![];

    for pattern in ignore_patterns {
        if let PatternSyntax::ExpandedSubInclude(sub_include) = pattern.syntax
        {
            subincludes.push(*sub_include);
        } else {
            others.push(pattern)
        }
    }
    Ok((subincludes, others))
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    #[test]
    fn escape_pattern_test() {
        let untouched =
            br#"!"%',/0123456789:;<=>@ABCDEFGHIJKLMNOPQRSTUVWXYZ_`abcdefghijklmnopqrstuvwxyz"#;
        assert_eq!(escape_pattern(untouched), untouched.to_vec());
        // All escape codes
        assert_eq!(
            escape_pattern(br"()[]{}?*+-|^$\\.&~#\t\n\r\v\f"),
            br"\(\)\[\]\{\}\?\*\+\-\|\^\$\\\\\.\&\~\#\\t\\n\\r\\v\\f".to_vec()
        );
    }

    #[test]
    fn glob_test() {
        assert_eq!(glob_to_re(br"?"), br".");
        assert_eq!(glob_to_re(br"*"), br"[^/]*");
        assert_eq!(glob_to_re(br"**"), br".*");
        assert_eq!(glob_to_re(br"**/a"), br"(?:.*/)?a");
        assert_eq!(glob_to_re(br"a/**/b"), br"a/(?:.*/)?b");
        assert_eq!(glob_to_re(br"[a*?!^][^b][!c]"), br"[a*?!^][\^b][^c]");
        assert_eq!(glob_to_re(br"{a,b}"), br"(?:a|b)");
        assert_eq!(glob_to_re(br".\*\?"), br"\.\*\?");
    }

    #[test]
    fn test_parse_pattern_file_contents() {
        let lines = b"syntax: glob\n*.elc";

        assert_eq!(
            parse_pattern_file_contents(
                lines,
                Path::new("file_path"),
                None,
                false,
                true,
            )
            .unwrap()
            .0,
            vec![IgnorePattern::new(
                PatternSyntax::RelGlob,
                b"*.elc",
                Path::new("file_path")
            )],
        );

        let lines = b"syntax: include\nsyntax: glob";

        assert_eq!(
            parse_pattern_file_contents(
                lines,
                Path::new("file_path"),
                None,
                false,
                true,
            )
            .unwrap()
            .0,
            vec![]
        );
        let lines = b"glob:**.o";
        assert_eq!(
            parse_pattern_file_contents(
                lines,
                Path::new("file_path"),
                None,
                false,
                true,
            )
            .unwrap()
            .0,
            vec![IgnorePattern::new(
                PatternSyntax::RelGlob,
                b"**.o",
                Path::new("file_path")
            )]
        );
    }

    #[test]
    fn test_build_single_regex() {
        assert_eq!(
            build_single_regex(
                &IgnorePattern::new(
                    PatternSyntax::RelGlob,
                    b"rust/target/",
                    Path::new("")
                ),
                b"(?:/|$)"
            )
            .unwrap(),
            Some(br"(?:.*/)?rust/target(?:/|$)".to_vec()),
        );
        assert_eq!(
            build_single_regex(
                &IgnorePattern::new(
                    PatternSyntax::Regexp,
                    br"rust/target/\d+",
                    Path::new("")
                ),
                b"(?:/|$)"
            )
            .unwrap(),
            Some(br"rust/target/\d+".to_vec()),
        );
    }

    #[test]
    fn test_build_single_regex_shortcut() {
        assert_eq!(
            build_single_regex(
                &IgnorePattern::new(
                    PatternSyntax::RootGlob,
                    b"",
                    Path::new("")
                ),
                b"(?:/|$)"
            )
            .unwrap(),
            None,
        );
        assert_eq!(
            build_single_regex(
                &IgnorePattern::new(
                    PatternSyntax::RootGlob,
                    b"whatever",
                    Path::new("")
                ),
                b"(?:/|$)"
            )
            .unwrap(),
            None,
        );
        assert_eq!(
            build_single_regex(
                &IgnorePattern::new(
                    PatternSyntax::RootGlob,
                    b"*.o",
                    Path::new("")
                ),
                b"(?:/|$)"
            )
            .unwrap(),
            Some(br"[^/]*\.o(?:/|$)".to_vec()),
        );
    }

    #[test]
    fn test_build_single_relregex() {
        assert_eq!(
            build_single_regex(
                &IgnorePattern::new(
                    PatternSyntax::RelRegexp,
                    b"^ba{2}r",
                    Path::new("")
                ),
                b"(?:/|$)"
            )
            .unwrap(),
            Some(b"^ba{2}r".to_vec()),
        );
        assert_eq!(
            build_single_regex(
                &IgnorePattern::new(
                    PatternSyntax::RelRegexp,
                    b"ba{2}r",
                    Path::new("")
                ),
                b"(?:/|$)"
            )
            .unwrap(),
            Some(b".*ba{2}r".to_vec()),
        );
        assert_eq!(
            build_single_regex(
                &IgnorePattern::new(
                    PatternSyntax::RelRegexp,
                    b"(?ia)ba{2}r",
                    Path::new("")
                ),
                b"(?:/|$)"
            )
            .unwrap(),
            Some(b"(?ia:.*ba{2}r)".to_vec()),
        );
        assert_eq!(
            build_single_regex(
                &IgnorePattern::new(
                    PatternSyntax::RelRegexp,
                    b"(?ia)^ba{2}r",
                    Path::new("")
                ),
                b"(?:/|$)"
            )
            .unwrap(),
            Some(b"(?ia:^ba{2}r)".to_vec()),
        );
    }
}
