pub mod files;

use std::convert::AsMut;

/// Takes a slice and copies it into an array.
///
/// # Panics
///
/// Will panic if the slice and target array don't have the same length.
pub fn copy_into_array<A, T>(slice: &[T]) -> A
where
    A: Sized + Default + AsMut<[T]>,
    T: Copy,
{
    let mut a = Default::default();
    <A as AsMut<[T]>>::as_mut(&mut a).copy_from_slice(slice);
    a
}

/// Replaces the `from` slice with the `to` slice inside the `buf` slice.
///
/// # Examples
///
/// ```
/// use crate::hg::utils::replace_slice;
/// let mut line = b"I hate writing tests!".to_vec();
/// replace_slice(&mut line, b"hate", b"love");
/// assert_eq!(
///     line,
///     b"I love writing tests!".to_vec()
///);
///
/// ```
pub fn replace_slice<T>(buf: &mut [T], from: &[T], to: &[T])
where
    T: Clone + PartialEq,
{
    if buf.len() < from.len() || from.len() != to.len() {
        return;
    }
    for i in 0..=buf.len() - from.len() {
        if buf[i..].starts_with(from) {
            buf[i..(i + from.len())].clone_from_slice(to);
        }
    }
}

pub trait SliceExt {
    fn trim_end(&self) -> &Self;
    fn trim_start(&self) -> &Self;
    fn trim(&self) -> &Self;
}

fn is_not_whitespace(c: &u8) -> bool {
    !(*c as char).is_whitespace()
}

impl SliceExt for [u8] {
    fn trim_end(&self) -> &[u8] {
        if let Some(last) = self.iter().rposition(is_not_whitespace) {
            &self[..last + 1]
        } else {
            &[]
        }
    }
    fn trim_start(&self) -> &[u8] {
        if let Some(first) = self.iter().position(is_not_whitespace) {
            &self[first..]
        } else {
            &[]
        }
    }

    /// ```
    /// use hg::utils::SliceExt;
    /// assert_eq!(
    ///     b"  to trim  ".trim(),
    ///     b"to trim"
    /// );
    /// assert_eq!(
    ///     b"to trim  ".trim(),
    ///     b"to trim"
    /// );
    /// assert_eq!(
    ///     b"  to trim".trim(),
    ///     b"to trim"
    /// );
    /// ```
    fn trim(&self) -> &[u8] {
        self.trim_start().trim_end()
    }
}
