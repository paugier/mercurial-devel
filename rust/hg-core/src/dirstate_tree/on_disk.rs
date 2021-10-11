//! The "version 2" disk representation of the dirstate
//!
//! See `mercurial/helptext/internals/dirstate-v2.txt`

use crate::dirstate_tree::dirstate_map::{self, DirstateMap, NodeRef};
use crate::dirstate_tree::path_with_basename::WithBasename;
use crate::errors::HgError;
use crate::utils::hg_path::HgPath;
use crate::DirstateEntry;
use crate::DirstateError;
use crate::DirstateParents;
use bitflags::bitflags;
use bytes_cast::unaligned::{I32Be, I64Be, U16Be, U32Be};
use bytes_cast::BytesCast;
use format_bytes::format_bytes;
use std::borrow::Cow;
use std::convert::{TryFrom, TryInto};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// Added at the start of `.hg/dirstate` when the "v2" format is used.
/// This a redundant sanity check more than an actual "magic number" since
/// `.hg/requires` already governs which format should be used.
pub const V2_FORMAT_MARKER: &[u8; 12] = b"dirstate-v2\n";

/// Keep space for 256-bit hashes
const STORED_NODE_ID_BYTES: usize = 32;

/// … even though only 160 bits are used for now, with SHA-1
const USED_NODE_ID_BYTES: usize = 20;

pub(super) const IGNORE_PATTERNS_HASH_LEN: usize = 20;
pub(super) type IgnorePatternsHash = [u8; IGNORE_PATTERNS_HASH_LEN];

/// Must match the constant of the same name in
/// `mercurial/dirstateutils/docket.py`
const TREE_METADATA_SIZE: usize = 44;

/// Make sure that size-affecting changes are made knowingly
#[allow(unused)]
fn static_assert_size_of() {
    let _ = std::mem::transmute::<TreeMetadata, [u8; TREE_METADATA_SIZE]>;
    let _ = std::mem::transmute::<DocketHeader, [u8; TREE_METADATA_SIZE + 81]>;
    let _ = std::mem::transmute::<Node, [u8; 43]>;
}

// Must match `HEADER` in `mercurial/dirstateutils/docket.py`
#[derive(BytesCast)]
#[repr(C)]
struct DocketHeader {
    marker: [u8; V2_FORMAT_MARKER.len()],
    parent_1: [u8; STORED_NODE_ID_BYTES],
    parent_2: [u8; STORED_NODE_ID_BYTES],

    metadata: TreeMetadata,

    /// Counted in bytes
    data_size: Size,

    uuid_size: u8,
}

pub struct Docket<'on_disk> {
    header: &'on_disk DocketHeader,
    uuid: &'on_disk [u8],
}

/// Fields are documented in the *Tree metadata in the docket file*
/// section of `mercurial/helptext/internals/dirstate-v2.txt`
#[derive(BytesCast)]
#[repr(C)]
struct TreeMetadata {
    root_nodes: ChildNodes,
    nodes_with_entry_count: Size,
    nodes_with_copy_source_count: Size,
    unreachable_bytes: Size,
    unused: [u8; 4],

    /// See *Optional hash of ignore patterns* section of
    /// `mercurial/helptext/internals/dirstate-v2.txt`
    ignore_patterns_hash: IgnorePatternsHash,
}

/// Fields are documented in the *The data file format*
/// section of `mercurial/helptext/internals/dirstate-v2.txt`
#[derive(BytesCast)]
#[repr(C)]
pub(super) struct Node {
    full_path: PathSlice,

    /// In bytes from `self.full_path.start`
    base_name_start: PathSize,

    copy_source: OptPathSlice,
    children: ChildNodes,
    pub(super) descendants_with_entry_count: Size,
    pub(super) tracked_descendants_count: Size,
    flags: Flags,
    data: Entry,
}

bitflags! {
    #[derive(BytesCast)]
    #[repr(C)]
    struct Flags: u8 {
        const WDIR_TRACKED = 1 << 0;
        const P1_TRACKED = 1 << 1;
        const P2_INFO = 1 << 2;
        const HAS_MODE_AND_SIZE = 1 << 3;
        const HAS_MTIME = 1 << 4;
    }
}

#[derive(BytesCast, Copy, Clone, Debug)]
#[repr(C)]
struct Entry {
    mode: I32Be,
    mtime: I32Be,
    size: I32Be,
}

/// Duration since the Unix epoch
#[derive(BytesCast, Copy, Clone, PartialEq)]
#[repr(C)]
pub(super) struct Timestamp {
    seconds: I64Be,

    /// In `0 .. 1_000_000_000`.
    ///
    /// This timestamp is later or earlier than `(seconds, 0)` by this many
    /// nanoseconds, if `seconds` is non-negative or negative, respectively.
    nanoseconds: U32Be,
}

/// Counted in bytes from the start of the file
///
/// NOTE: not supporting `.hg/dirstate` files larger than 4 GiB.
type Offset = U32Be;

/// Counted in number of items
///
/// NOTE: we choose not to support counting more than 4 billion nodes anywhere.
type Size = U32Be;

/// Counted in bytes
///
/// NOTE: we choose not to support file names/paths longer than 64 KiB.
type PathSize = U16Be;

/// A contiguous sequence of `len` times `Node`, representing the child nodes
/// of either some other node or of the repository root.
///
/// Always sorted by ascending `full_path`, to allow binary search.
/// Since nodes with the same parent nodes also have the same parent path,
/// only the `base_name`s need to be compared during binary search.
#[derive(BytesCast, Copy, Clone)]
#[repr(C)]
struct ChildNodes {
    start: Offset,
    len: Size,
}

/// A `HgPath` of `len` bytes
#[derive(BytesCast, Copy, Clone)]
#[repr(C)]
struct PathSlice {
    start: Offset,
    len: PathSize,
}

/// Either nothing if `start == 0`, or a `HgPath` of `len` bytes
type OptPathSlice = PathSlice;

/// Unexpected file format found in `.hg/dirstate` with the "v2" format.
///
/// This should only happen if Mercurial is buggy or a repository is corrupted.
#[derive(Debug)]
pub struct DirstateV2ParseError;

impl From<DirstateV2ParseError> for HgError {
    fn from(_: DirstateV2ParseError) -> Self {
        HgError::corrupted("dirstate-v2 parse error")
    }
}

impl From<DirstateV2ParseError> for crate::DirstateError {
    fn from(error: DirstateV2ParseError) -> Self {
        HgError::from(error).into()
    }
}

impl<'on_disk> Docket<'on_disk> {
    pub fn parents(&self) -> DirstateParents {
        use crate::Node;
        let p1 = Node::try_from(&self.header.parent_1[..USED_NODE_ID_BYTES])
            .unwrap()
            .clone();
        let p2 = Node::try_from(&self.header.parent_2[..USED_NODE_ID_BYTES])
            .unwrap()
            .clone();
        DirstateParents { p1, p2 }
    }

    pub fn tree_metadata(&self) -> &[u8] {
        self.header.metadata.as_bytes()
    }

    pub fn data_size(&self) -> usize {
        // This `unwrap` could only panic on a 16-bit CPU
        self.header.data_size.get().try_into().unwrap()
    }

    pub fn data_filename(&self) -> String {
        String::from_utf8(format_bytes!(b"dirstate.{}", self.uuid)).unwrap()
    }
}

pub fn read_docket(
    on_disk: &[u8],
) -> Result<Docket<'_>, DirstateV2ParseError> {
    let (header, uuid) =
        DocketHeader::from_bytes(on_disk).map_err(|_| DirstateV2ParseError)?;
    let uuid_size = header.uuid_size as usize;
    if header.marker == *V2_FORMAT_MARKER && uuid.len() == uuid_size {
        Ok(Docket { header, uuid })
    } else {
        Err(DirstateV2ParseError)
    }
}

pub(super) fn read<'on_disk>(
    on_disk: &'on_disk [u8],
    metadata: &[u8],
) -> Result<DirstateMap<'on_disk>, DirstateV2ParseError> {
    if on_disk.is_empty() {
        return Ok(DirstateMap::empty(on_disk));
    }
    let (meta, _) = TreeMetadata::from_bytes(metadata)
        .map_err(|_| DirstateV2ParseError)?;
    let dirstate_map = DirstateMap {
        on_disk,
        root: dirstate_map::ChildNodes::OnDisk(read_nodes(
            on_disk,
            meta.root_nodes,
        )?),
        nodes_with_entry_count: meta.nodes_with_entry_count.get(),
        nodes_with_copy_source_count: meta.nodes_with_copy_source_count.get(),
        ignore_patterns_hash: meta.ignore_patterns_hash,
        unreachable_bytes: meta.unreachable_bytes.get(),
    };
    Ok(dirstate_map)
}

impl Node {
    pub(super) fn full_path<'on_disk>(
        &self,
        on_disk: &'on_disk [u8],
    ) -> Result<&'on_disk HgPath, DirstateV2ParseError> {
        read_hg_path(on_disk, self.full_path)
    }

    pub(super) fn base_name_start<'on_disk>(
        &self,
    ) -> Result<usize, DirstateV2ParseError> {
        let start = self.base_name_start.get();
        if start < self.full_path.len.get() {
            let start = usize::try_from(start)
                // u32 -> usize, could only panic on a 16-bit CPU
                .expect("dirstate-v2 base_name_start out of bounds");
            Ok(start)
        } else {
            Err(DirstateV2ParseError)
        }
    }

    pub(super) fn base_name<'on_disk>(
        &self,
        on_disk: &'on_disk [u8],
    ) -> Result<&'on_disk HgPath, DirstateV2ParseError> {
        let full_path = self.full_path(on_disk)?;
        let base_name_start = self.base_name_start()?;
        Ok(HgPath::new(&full_path.as_bytes()[base_name_start..]))
    }

    pub(super) fn path<'on_disk>(
        &self,
        on_disk: &'on_disk [u8],
    ) -> Result<dirstate_map::NodeKey<'on_disk>, DirstateV2ParseError> {
        Ok(WithBasename::from_raw_parts(
            Cow::Borrowed(self.full_path(on_disk)?),
            self.base_name_start()?,
        ))
    }

    pub(super) fn has_copy_source<'on_disk>(&self) -> bool {
        self.copy_source.start.get() != 0
    }

    pub(super) fn copy_source<'on_disk>(
        &self,
        on_disk: &'on_disk [u8],
    ) -> Result<Option<&'on_disk HgPath>, DirstateV2ParseError> {
        Ok(if self.has_copy_source() {
            Some(read_hg_path(on_disk, self.copy_source)?)
        } else {
            None
        })
    }

    fn has_entry(&self) -> bool {
        self.flags.intersects(
            Flags::WDIR_TRACKED | Flags::P1_TRACKED | Flags::P2_INFO,
        )
    }

    pub(super) fn node_data(
        &self,
    ) -> Result<dirstate_map::NodeData, DirstateV2ParseError> {
        if self.has_entry() {
            Ok(dirstate_map::NodeData::Entry(self.assume_entry()))
        } else if let Some(&mtime) = self.cached_directory_mtime() {
            Ok(dirstate_map::NodeData::CachedDirectory { mtime })
        } else {
            Ok(dirstate_map::NodeData::None)
        }
    }

    pub(super) fn cached_directory_mtime(&self) -> Option<&Timestamp> {
        if self.flags.contains(Flags::HAS_MTIME) && !self.has_entry() {
            Some(self.data.as_timestamp())
        } else {
            None
        }
    }

    fn assume_entry(&self) -> DirstateEntry {
        // TODO: convert through raw bits instead?
        let wdir_tracked = self.flags.contains(Flags::WDIR_TRACKED);
        let p1_tracked = self.flags.contains(Flags::P1_TRACKED);
        let p2_info = self.flags.contains(Flags::P2_INFO);
        let mode_size = if self.flags.contains(Flags::HAS_MODE_AND_SIZE) {
            Some((self.data.mode.into(), self.data.size.into()))
        } else {
            None
        };
        let mtime = if self.flags.contains(Flags::HAS_MTIME) {
            Some(self.data.mtime.into())
        } else {
            None
        };
        DirstateEntry::from_v2_data(
            wdir_tracked,
            p1_tracked,
            p2_info,
            mode_size,
            mtime,
        )
    }

    pub(super) fn entry(
        &self,
    ) -> Result<Option<DirstateEntry>, DirstateV2ParseError> {
        if self.has_entry() {
            Ok(Some(self.assume_entry()))
        } else {
            Ok(None)
        }
    }

    pub(super) fn children<'on_disk>(
        &self,
        on_disk: &'on_disk [u8],
    ) -> Result<&'on_disk [Node], DirstateV2ParseError> {
        read_nodes(on_disk, self.children)
    }

    pub(super) fn to_in_memory_node<'on_disk>(
        &self,
        on_disk: &'on_disk [u8],
    ) -> Result<dirstate_map::Node<'on_disk>, DirstateV2ParseError> {
        Ok(dirstate_map::Node {
            children: dirstate_map::ChildNodes::OnDisk(
                self.children(on_disk)?,
            ),
            copy_source: self.copy_source(on_disk)?.map(Cow::Borrowed),
            data: self.node_data()?,
            descendants_with_entry_count: self
                .descendants_with_entry_count
                .get(),
            tracked_descendants_count: self.tracked_descendants_count.get(),
        })
    }
}

impl Entry {
    fn from_dirstate_entry(entry: &DirstateEntry) -> (Flags, Self) {
        let (wdir_tracked, p1_tracked, p2_info, mode_size_opt, mtime_opt) =
            entry.v2_data();
        // TODO: convert throug raw flag bits instead?
        let mut flags = Flags::empty();
        flags.set(Flags::WDIR_TRACKED, wdir_tracked);
        flags.set(Flags::P1_TRACKED, p1_tracked);
        flags.set(Flags::P2_INFO, p2_info);
        let (mode, size, mtime);
        if let Some((m, s)) = mode_size_opt {
            mode = m;
            size = s;
            flags.insert(Flags::HAS_MODE_AND_SIZE)
        } else {
            mode = 0;
            size = 0;
        }
        if let Some(m) = mtime_opt {
            mtime = m;
            flags.insert(Flags::HAS_MTIME);
        } else {
            mtime = 0;
        }
        let raw_entry = Entry {
            mode: mode.into(),
            size: size.into(),
            mtime: mtime.into(),
        };
        (flags, raw_entry)
    }

    fn from_timestamp(timestamp: Timestamp) -> Self {
        // Safety: both types implement the `ByteCast` trait, so we could
        // safely use `as_bytes` and `from_bytes` to do this conversion. Using
        // `transmute` instead makes the compiler check that the two types
        // have the same size, which eliminates the error case of
        // `from_bytes`.
        unsafe { std::mem::transmute::<Timestamp, Entry>(timestamp) }
    }

    fn as_timestamp(&self) -> &Timestamp {
        // Safety: same as above in `from_timestamp`
        unsafe { &*(self as *const Entry as *const Timestamp) }
    }
}

impl Timestamp {
    pub fn seconds(&self) -> i64 {
        self.seconds.get()
    }
}

impl From<SystemTime> for Timestamp {
    fn from(system_time: SystemTime) -> Self {
        let (secs, nanos) = match system_time.duration_since(UNIX_EPOCH) {
            Ok(duration) => {
                (duration.as_secs() as i64, duration.subsec_nanos())
            }
            Err(error) => {
                let negative = error.duration();
                (-(negative.as_secs() as i64), negative.subsec_nanos())
            }
        };
        Timestamp {
            seconds: secs.into(),
            nanoseconds: nanos.into(),
        }
    }
}

impl From<&'_ Timestamp> for SystemTime {
    fn from(timestamp: &'_ Timestamp) -> Self {
        let secs = timestamp.seconds.get();
        let nanos = timestamp.nanoseconds.get();
        if secs >= 0 {
            UNIX_EPOCH + Duration::new(secs as u64, nanos)
        } else {
            UNIX_EPOCH - Duration::new((-secs) as u64, nanos)
        }
    }
}

fn read_hg_path(
    on_disk: &[u8],
    slice: PathSlice,
) -> Result<&HgPath, DirstateV2ParseError> {
    read_slice(on_disk, slice.start, slice.len.get()).map(HgPath::new)
}

fn read_nodes(
    on_disk: &[u8],
    slice: ChildNodes,
) -> Result<&[Node], DirstateV2ParseError> {
    read_slice(on_disk, slice.start, slice.len.get())
}

fn read_slice<T, Len>(
    on_disk: &[u8],
    start: Offset,
    len: Len,
) -> Result<&[T], DirstateV2ParseError>
where
    T: BytesCast,
    Len: TryInto<usize>,
{
    // Either `usize::MAX` would result in "out of bounds" error since a single
    // `&[u8]` cannot occupy the entire addess space.
    let start = start.get().try_into().unwrap_or(std::usize::MAX);
    let len = len.try_into().unwrap_or(std::usize::MAX);
    on_disk
        .get(start..)
        .and_then(|bytes| T::slice_from_bytes(bytes, len).ok())
        .map(|(slice, _rest)| slice)
        .ok_or_else(|| DirstateV2ParseError)
}

pub(crate) fn for_each_tracked_path<'on_disk>(
    on_disk: &'on_disk [u8],
    metadata: &[u8],
    mut f: impl FnMut(&'on_disk HgPath),
) -> Result<(), DirstateV2ParseError> {
    let (meta, _) = TreeMetadata::from_bytes(metadata)
        .map_err(|_| DirstateV2ParseError)?;
    fn recur<'on_disk>(
        on_disk: &'on_disk [u8],
        nodes: ChildNodes,
        f: &mut impl FnMut(&'on_disk HgPath),
    ) -> Result<(), DirstateV2ParseError> {
        for node in read_nodes(on_disk, nodes)? {
            if let Some(entry) = node.entry()? {
                if entry.state().is_tracked() {
                    f(node.full_path(on_disk)?)
                }
            }
            recur(on_disk, node.children, f)?
        }
        Ok(())
    }
    recur(on_disk, meta.root_nodes, &mut f)
}

/// Returns new data and metadata, together with whether that data should be
/// appended to the existing data file whose content is at
/// `dirstate_map.on_disk` (true), instead of written to a new data file
/// (false).
pub(super) fn write(
    dirstate_map: &mut DirstateMap,
    can_append: bool,
) -> Result<(Vec<u8>, Vec<u8>, bool), DirstateError> {
    let append = can_append && dirstate_map.write_should_append();

    // This ignores the space for paths, and for nodes without an entry.
    // TODO: better estimate? Skip the `Vec` and write to a file directly?
    let size_guess = std::mem::size_of::<Node>()
        * dirstate_map.nodes_with_entry_count as usize;

    let mut writer = Writer {
        dirstate_map,
        append,
        out: Vec::with_capacity(size_guess),
    };

    let root_nodes = writer.write_nodes(dirstate_map.root.as_ref())?;

    let meta = TreeMetadata {
        root_nodes,
        nodes_with_entry_count: dirstate_map.nodes_with_entry_count.into(),
        nodes_with_copy_source_count: dirstate_map
            .nodes_with_copy_source_count
            .into(),
        unreachable_bytes: dirstate_map.unreachable_bytes.into(),
        unused: [0; 4],
        ignore_patterns_hash: dirstate_map.ignore_patterns_hash,
    };
    Ok((writer.out, meta.as_bytes().to_vec(), append))
}

struct Writer<'dmap, 'on_disk> {
    dirstate_map: &'dmap DirstateMap<'on_disk>,
    append: bool,
    out: Vec<u8>,
}

impl Writer<'_, '_> {
    fn write_nodes(
        &mut self,
        nodes: dirstate_map::ChildNodesRef,
    ) -> Result<ChildNodes, DirstateError> {
        // Reuse already-written nodes if possible
        if self.append {
            if let dirstate_map::ChildNodesRef::OnDisk(nodes_slice) = nodes {
                let start = self.on_disk_offset_of(nodes_slice).expect(
                    "dirstate-v2 OnDisk nodes not found within on_disk",
                );
                let len = child_nodes_len_from_usize(nodes_slice.len());
                return Ok(ChildNodes { start, len });
            }
        }

        // `dirstate_map::ChildNodes::InMemory` contains a `HashMap` which has
        // undefined iteration order. Sort to enable binary search in the
        // written file.
        let nodes = nodes.sorted();
        let nodes_len = nodes.len();

        // First accumulate serialized nodes in a `Vec`
        let mut on_disk_nodes = Vec::with_capacity(nodes_len);
        for node in nodes {
            let children =
                self.write_nodes(node.children(self.dirstate_map.on_disk)?)?;
            let full_path = node.full_path(self.dirstate_map.on_disk)?;
            let full_path = self.write_path(full_path.as_bytes());
            let copy_source = if let Some(source) =
                node.copy_source(self.dirstate_map.on_disk)?
            {
                self.write_path(source.as_bytes())
            } else {
                PathSlice {
                    start: 0.into(),
                    len: 0.into(),
                }
            };
            on_disk_nodes.push(match node {
                NodeRef::InMemory(path, node) => {
                    let (flags, data) = match &node.data {
                        dirstate_map::NodeData::Entry(entry) => {
                            Entry::from_dirstate_entry(entry)
                        }
                        dirstate_map::NodeData::CachedDirectory { mtime } => {
                            (Flags::HAS_MTIME, Entry::from_timestamp(*mtime))
                        }
                        dirstate_map::NodeData::None => (
                            Flags::empty(),
                            Entry {
                                mode: 0.into(),
                                size: 0.into(),
                                mtime: 0.into(),
                            },
                        ),
                    };
                    Node {
                        children,
                        copy_source,
                        full_path,
                        base_name_start: u16::try_from(path.base_name_start())
                            // Could only panic for paths over 64 KiB
                            .expect("dirstate-v2 path length overflow")
                            .into(),
                        descendants_with_entry_count: node
                            .descendants_with_entry_count
                            .into(),
                        tracked_descendants_count: node
                            .tracked_descendants_count
                            .into(),
                        flags,
                        data,
                    }
                }
                NodeRef::OnDisk(node) => Node {
                    children,
                    copy_source,
                    full_path,
                    ..*node
                },
            })
        }
        // … so we can write them contiguously, after writing everything else
        // they refer to.
        let start = self.current_offset();
        let len = child_nodes_len_from_usize(nodes_len);
        self.out.extend(on_disk_nodes.as_bytes());
        Ok(ChildNodes { start, len })
    }

    /// If the given slice of items is within `on_disk`, returns its offset
    /// from the start of `on_disk`.
    fn on_disk_offset_of<T>(&self, slice: &[T]) -> Option<Offset>
    where
        T: BytesCast,
    {
        fn address_range(slice: &[u8]) -> std::ops::RangeInclusive<usize> {
            let start = slice.as_ptr() as usize;
            let end = start + slice.len();
            start..=end
        }
        let slice_addresses = address_range(slice.as_bytes());
        let on_disk_addresses = address_range(self.dirstate_map.on_disk);
        if on_disk_addresses.contains(slice_addresses.start())
            && on_disk_addresses.contains(slice_addresses.end())
        {
            let offset = slice_addresses.start() - on_disk_addresses.start();
            Some(offset_from_usize(offset))
        } else {
            None
        }
    }

    fn current_offset(&mut self) -> Offset {
        let mut offset = self.out.len();
        if self.append {
            offset += self.dirstate_map.on_disk.len()
        }
        offset_from_usize(offset)
    }

    fn write_path(&mut self, slice: &[u8]) -> PathSlice {
        let len = path_len_from_usize(slice.len());
        // Reuse an already-written path if possible
        if self.append {
            if let Some(start) = self.on_disk_offset_of(slice) {
                return PathSlice { start, len };
            }
        }
        let start = self.current_offset();
        self.out.extend(slice.as_bytes());
        PathSlice { start, len }
    }
}

fn offset_from_usize(x: usize) -> Offset {
    u32::try_from(x)
        // Could only panic for a dirstate file larger than 4 GiB
        .expect("dirstate-v2 offset overflow")
        .into()
}

fn child_nodes_len_from_usize(x: usize) -> Size {
    u32::try_from(x)
        // Could only panic with over 4 billion nodes
        .expect("dirstate-v2 slice length overflow")
        .into()
}

fn path_len_from_usize(x: usize) -> PathSize {
    u16::try_from(x)
        // Could only panic for paths over 64 KiB
        .expect("dirstate-v2 path length overflow")
        .into()
}
