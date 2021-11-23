use crate::errors::{HgError, IoErrorContext, IoResultExt};
use memmap2::{Mmap, MmapOptions};
use std::io::ErrorKind;
use std::path::{Path, PathBuf};

/// Filesystem access abstraction for the contents of a given "base" diretory
#[derive(Clone, Copy)]
pub struct Vfs<'a> {
    pub(crate) base: &'a Path,
}

struct FileNotFound(std::io::Error, PathBuf);

impl Vfs<'_> {
    pub fn join(&self, relative_path: impl AsRef<Path>) -> PathBuf {
        self.base.join(relative_path)
    }

    pub fn symlink_metadata(
        &self,
        relative_path: impl AsRef<Path>,
    ) -> Result<std::fs::Metadata, HgError> {
        let path = self.join(relative_path);
        std::fs::symlink_metadata(&path).when_reading_file(&path)
    }

    pub fn read_link(
        &self,
        relative_path: impl AsRef<Path>,
    ) -> Result<PathBuf, HgError> {
        let path = self.join(relative_path);
        std::fs::read_link(&path).when_reading_file(&path)
    }

    pub fn read(
        &self,
        relative_path: impl AsRef<Path>,
    ) -> Result<Vec<u8>, HgError> {
        let path = self.join(relative_path);
        std::fs::read(&path).when_reading_file(&path)
    }

    fn mmap_open_gen(
        &self,
        relative_path: impl AsRef<Path>,
    ) -> Result<Result<Mmap, FileNotFound>, HgError> {
        let path = self.join(relative_path);
        let file = match std::fs::File::open(&path) {
            Err(err) => {
                if let ErrorKind::NotFound = err.kind() {
                    return Ok(Err(FileNotFound(err, path)));
                };
                return (Err(err)).when_reading_file(&path);
            }
            Ok(file) => file,
        };
        // TODO: what are the safety requirements here?
        let mmap = unsafe { MmapOptions::new().map(&file) }
            .when_reading_file(&path)?;
        Ok(Ok(mmap))
    }

    pub fn mmap_open_opt(
        &self,
        relative_path: impl AsRef<Path>,
    ) -> Result<Option<Mmap>, HgError> {
        self.mmap_open_gen(relative_path).map(|res| res.ok())
    }

    pub fn mmap_open(
        &self,
        relative_path: impl AsRef<Path>,
    ) -> Result<Mmap, HgError> {
        match self.mmap_open_gen(relative_path)? {
            Err(FileNotFound(err, path)) => Err(err).when_reading_file(&path),
            Ok(res) => Ok(res),
        }
    }

    pub fn rename(
        &self,
        relative_from: impl AsRef<Path>,
        relative_to: impl AsRef<Path>,
    ) -> Result<(), HgError> {
        let from = self.join(relative_from);
        let to = self.join(relative_to);
        std::fs::rename(&from, &to)
            .with_context(|| IoErrorContext::RenamingFile { from, to })
    }
}

fn fs_metadata(
    path: impl AsRef<Path>,
) -> Result<Option<std::fs::Metadata>, HgError> {
    let path = path.as_ref();
    match std::fs::metadata(path) {
        Ok(meta) => Ok(Some(meta)),
        Err(error) => match error.kind() {
            // TODO: when we require a Rust version where `NotADirectory` is
            // stable, invert this logic and return None for it and `NotFound`
            // and propagate any other error.
            ErrorKind::PermissionDenied => Err(error).with_context(|| {
                IoErrorContext::ReadingMetadata(path.to_owned())
            }),
            _ => Ok(None),
        },
    }
}

pub(crate) fn is_dir(path: impl AsRef<Path>) -> Result<bool, HgError> {
    Ok(fs_metadata(path)?.map_or(false, |meta| meta.is_dir()))
}

pub(crate) fn is_file(path: impl AsRef<Path>) -> Result<bool, HgError> {
    Ok(fs_metadata(path)?.map_or(false, |meta| meta.is_file()))
}
