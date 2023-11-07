use crate::color::ColorConfig;
use crate::color::Effect;
use crate::error::CommandError;
use format_bytes::format_bytes;
use format_bytes::write_bytes;
use hg::config::Config;
use hg::config::PlainInfo;
use hg::errors::HgError;
use hg::repo::Repo;
use hg::sparse;
use hg::utils::files::get_bytes_from_path;
use hg::PatternFileWarning;
use std::borrow::Cow;
use std::io;
use std::io::{ErrorKind, Write};

pub struct Ui {
    stdout: std::io::Stdout,
    stderr: std::io::Stderr,
    colors: Option<ColorConfig>,
}

/// The kind of user interface error
pub enum UiError {
    /// The standard output stream cannot be written to
    StdoutError(io::Error),
    /// The standard error stream cannot be written to
    StderrError(io::Error),
}

/// The commandline user interface
impl Ui {
    pub fn new(config: &Config) -> Result<Self, HgError> {
        Ok(Ui {
            // If using something else, also adapt `isatty()` below.
            stdout: std::io::stdout(),

            stderr: std::io::stderr(),
            colors: ColorConfig::new(config)?,
        })
    }

    /// Default to no color if color configuration errors.
    ///
    /// Useful when we’re already handling another error.
    pub fn new_infallible(config: &Config) -> Self {
        Ui {
            // If using something else, also adapt `isatty()` below.
            stdout: std::io::stdout(),

            stderr: std::io::stderr(),
            colors: ColorConfig::new(config).unwrap_or(None),
        }
    }

    /// Returns a buffered handle on stdout for faster batch printing
    /// operations.
    pub fn stdout_buffer(&self) -> StdoutBuffer<std::io::StdoutLock> {
        StdoutBuffer::new(self.stdout.lock())
    }

    /// Write bytes to stdout
    pub fn write_stdout(&self, bytes: &[u8]) -> Result<(), UiError> {
        let mut stdout = self.stdout.lock();

        stdout.write_all(bytes).or_else(handle_stdout_error)?;

        stdout.flush().or_else(handle_stdout_error)
    }

    /// Write bytes to stderr
    pub fn write_stderr(&self, bytes: &[u8]) -> Result<(), UiError> {
        let mut stderr = self.stderr.lock();

        stderr.write_all(bytes).or_else(handle_stderr_error)?;

        stderr.flush().or_else(handle_stderr_error)
    }

    /// Write bytes to stdout with the given label
    ///
    /// Like the optional `label` parameter in `mercurial/ui.py`,
    /// this label influences the color used for this output.
    pub fn write_stdout_labelled(
        &self,
        bytes: &[u8],
        label: &str,
    ) -> Result<(), UiError> {
        if let Some(colors) = &self.colors {
            if let Some(effects) = colors.styles.get(label.as_bytes()) {
                if !effects.is_empty() {
                    return self
                        .write_stdout_with_effects(bytes, effects)
                        .or_else(handle_stdout_error);
                }
            }
        }
        self.write_stdout(bytes)
    }

    fn write_stdout_with_effects(
        &self,
        bytes: &[u8],
        effects: &[Effect],
    ) -> io::Result<()> {
        let stdout = &mut self.stdout.lock();
        let mut write_line = |line: &[u8], first: bool| {
            // `line` does not include the newline delimiter
            if !first {
                stdout.write_all(b"\n")?;
            }
            if line.is_empty() {
                return Ok(());
            }
            /// 0x1B == 27 == 0o33
            const ASCII_ESCAPE: &[u8] = b"\x1b";
            write_bytes!(stdout, b"{}[0", ASCII_ESCAPE)?;
            for effect in effects {
                write_bytes!(stdout, b";{}", effect)?;
            }
            write_bytes!(stdout, b"m")?;
            stdout.write_all(line)?;
            write_bytes!(stdout, b"{}[0m", ASCII_ESCAPE)
        };
        let mut lines = bytes.split(|&byte| byte == b'\n');
        if let Some(first) = lines.next() {
            write_line(first, true)?;
            for line in lines {
                write_line(line, false)?
            }
        }
        stdout.flush()
    }
}

// TODO: pass the PlainInfo to call sites directly and
// delete this function
pub fn plain(opt_feature: Option<&str>) -> bool {
    let plain_info = PlainInfo::from_env();
    match opt_feature {
        None => plain_info.is_plain(),
        Some(feature) => plain_info.is_feature_plain(feature),
    }
}

/// A buffered stdout writer for faster batch printing operations.
pub struct StdoutBuffer<W: Write> {
    buf: io::BufWriter<W>,
}

impl<W: Write> StdoutBuffer<W> {
    pub fn new(writer: W) -> Self {
        let buf = io::BufWriter::new(writer);
        Self { buf }
    }

    /// Write bytes to stdout buffer
    pub fn write_all(&mut self, bytes: &[u8]) -> Result<(), UiError> {
        self.buf.write_all(bytes).or_else(handle_stdout_error)
    }

    /// Flush bytes to stdout
    pub fn flush(&mut self) -> Result<(), UiError> {
        self.buf.flush().or_else(handle_stdout_error)
    }
}

/// Sometimes writing to stdout is not possible, try writing to stderr to
/// signal that failure, otherwise just bail.
fn handle_stdout_error(error: io::Error) -> Result<(), UiError> {
    if let ErrorKind::BrokenPipe = error.kind() {
        // This makes `| head` work for example
        return Ok(());
    }
    let mut stderr = io::stderr();

    stderr
        .write_all(&format_bytes!(
            b"abort: {}\n",
            error.to_string().as_bytes()
        ))
        .map_err(UiError::StderrError)?;

    stderr.flush().map_err(UiError::StderrError)?;

    Err(UiError::StdoutError(error))
}

/// Sometimes writing to stderr is not possible.
fn handle_stderr_error(error: io::Error) -> Result<(), UiError> {
    // A broken pipe should not result in a error
    // like with `| head` for example
    if let ErrorKind::BrokenPipe = error.kind() {
        return Ok(());
    }
    Err(UiError::StdoutError(error))
}

/// Encode rust strings according to the user system.
pub fn utf8_to_local(s: &str) -> Cow<[u8]> {
    // TODO encode for the user's system //
    let bytes = s.as_bytes();
    Cow::Borrowed(bytes)
}

/// Decode user system bytes to Rust string.
pub fn local_to_utf8(s: &[u8]) -> Cow<str> {
    // TODO decode from the user's system
    String::from_utf8_lossy(s)
}

/// Should formatted output be used?
///
/// Note: rhg does not have the formatter mechanism yet,
/// but this is also used when deciding whether to use color.
pub fn formatted(config: &Config) -> Result<bool, HgError> {
    if let Some(formatted) = config.get_option(b"ui", b"formatted")? {
        Ok(formatted)
    } else {
        isatty(config)
    }
}

pub enum RelativePaths {
    Legacy,
    Bool(bool),
}

pub fn relative_paths(config: &Config) -> Result<RelativePaths, HgError> {
    Ok(match config.get(b"ui", b"relative-paths") {
        None | Some(b"legacy") => RelativePaths::Legacy,
        _ => RelativePaths::Bool(config.get_bool(b"ui", b"relative-paths")?),
    })
}

fn isatty(config: &Config) -> Result<bool, HgError> {
    Ok(if config.get_bool(b"ui", b"nontty")? {
        false
    } else {
        atty::is(atty::Stream::Stdout)
    })
}

/// Return the formatted bytestring corresponding to a pattern file warning,
/// as expected by the CLI.
pub(crate) fn format_pattern_file_warning(
    warning: &PatternFileWarning,
    repo: &Repo,
) -> Vec<u8> {
    match warning {
        PatternFileWarning::InvalidSyntax(path, syntax) => format_bytes!(
            b"{}: ignoring invalid syntax '{}'\n",
            get_bytes_from_path(path),
            syntax
        ),
        PatternFileWarning::NoSuchFile(path) => {
            let path = if let Ok(relative) =
                path.strip_prefix(repo.working_directory_path())
            {
                relative
            } else {
                path
            };
            format_bytes!(
                b"skipping unreadable pattern file '{}': \
                    No such file or directory\n",
                get_bytes_from_path(path),
            )
        }
    }
}

/// Print with `Ui` the formatted bytestring corresponding to a
/// sparse/narrow warning, as expected by the CLI.
pub(crate) fn print_narrow_sparse_warnings(
    narrow_warnings: &[sparse::SparseWarning],
    sparse_warnings: &[sparse::SparseWarning],
    ui: &Ui,
    repo: &Repo,
) -> Result<(), CommandError> {
    for warning in narrow_warnings.iter().chain(sparse_warnings) {
        match &warning {
            sparse::SparseWarning::RootWarning { context, line } => {
                let msg = format_bytes!(
                    b"warning: {} profile cannot use paths \"
                starting with /, ignoring {}\n",
                    context,
                    line
                );
                ui.write_stderr(&msg)?;
            }
            sparse::SparseWarning::ProfileNotFound { profile, rev } => {
                let msg = format_bytes!(
                    b"warning: sparse profile '{}' not found \"
                in rev {} - ignoring it\n",
                    profile,
                    rev
                );
                ui.write_stderr(&msg)?;
            }
            sparse::SparseWarning::Pattern(e) => {
                ui.write_stderr(&format_pattern_file_warning(e, repo))?;
            }
        }
    }
    Ok(())
}
