//! Rectangle-style window management for other apps' windows. Layout math lives here; the
//! native layer only reads and sets the focused window's frame through Accessibility.

use std::collections::HashMap;

pub const ACTION_PREFIX: &str = "window.";
const MAX_RESTORE_ENTRIES: usize = 32;
const MAX_SCREENS: usize = 16;
const RESIZE_STEP_PERCENT: i64 = 5;
const MIN_WINDOW_PERCENT: i64 = 25;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rect {
    pub x: i64,
    pub y: i64,
    pub w: i64,
    pub h: i64,
}

impl Rect {
    pub const fn new(x: i64, y: i64, w: i64, h: i64) -> Self {
        Self { x, y, w, h }
    }
    fn right(self) -> i64 {
        self.x + self.w
    }
    fn bottom(self) -> i64 {
        self.y + self.h
    }
    fn center(self) -> (i64, i64) {
        (self.x + self.w / 2, self.y + self.h / 2)
    }
    fn overlap_area(self, other: Rect) -> i64 {
        let width = (self.right().min(other.right()) - self.x.max(other.x)).max(0);
        let height = (self.bottom().min(other.bottom()) - self.y.max(other.y)).max(0);
        width * height
    }
}

/// Layout names, in the order shown in the shortcut editor. Actions are `window.<name>`.
pub const LAYOUTS: &[&str] = &[
    "left-half",
    "right-half",
    "top-half",
    "bottom-half",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "maximize",
    "center",
    "first-third",
    "center-third",
    "last-third",
    "first-two-thirds",
    "last-two-thirds",
    "center-half",
    "almost-maximize",
    "maximize-height",
    "larger",
    "smaller",
    "move-left",
    "move-right",
    "move-up",
    "move-down",
    "restore",
    "next-display",
    "previous-display",
];

/// Rectangle's default shortcuts: (layout, macOS key code, modifier mask ⌃=1 ⌥=2 ⇧=4 ⌘=8).
/// Layouts missing here (center half, almost maximize, move) start unassigned.
pub const DEFAULT_SHORTCUTS: &[(&str, u16, u8)] = &[
    ("left-half", 123, 0b0011),
    ("right-half", 124, 0b0011),
    ("top-half", 126, 0b0011),
    ("bottom-half", 125, 0b0011),
    ("top-left", 32, 0b0011),
    ("top-right", 34, 0b0011),
    ("bottom-left", 38, 0b0011),
    ("bottom-right", 40, 0b0011),
    ("maximize", 36, 0b0011),
    ("center", 8, 0b0011),
    ("first-third", 2, 0b0011),
    ("center-third", 3, 0b0011),
    ("last-third", 5, 0b0011),
    ("first-two-thirds", 14, 0b0011),
    ("last-two-thirds", 17, 0b0011),
    ("maximize-height", 126, 0b0111),
    ("larger", 24, 0b0011),
    ("smaller", 27, 0b0011),
    ("restore", 51, 0b0011),
    ("next-display", 124, 0b1011),
    ("previous-display", 123, 0b1011),
];

pub fn action_name(layout: &str) -> String {
    format!("{ACTION_PREFIX}{layout}")
}

pub fn layout_of(action: &str) -> Option<&'static str> {
    let name = action.strip_prefix(ACTION_PREFIX)?;
    LAYOUTS.iter().copied().find(|layout| *layout == name)
}

/// Layouts that tile the screen, so the configured gap applies to them.
fn uses_gap(layout: &str) -> bool {
    matches!(
        layout,
        "left-half"
            | "right-half"
            | "top-half"
            | "bottom-half"
            | "top-left"
            | "top-right"
            | "bottom-left"
            | "bottom-right"
            | "maximize"
            | "first-third"
            | "center-third"
            | "last-third"
            | "first-two-thirds"
            | "last-two-thirds"
            | "center-half"
    )
}

/// Insets a tile: the full gap against the screen edge and half a gap against a neighbour.
fn apply_gap(tile: Rect, area: Rect, gap: i64) -> Rect {
    if gap <= 0 {
        return tile;
    }
    let inset = |touches_edge: bool| if touches_edge { gap } else { gap / 2 };
    let left = inset(tile.x == area.x);
    let top = inset(tile.y == area.y);
    let right = inset(tile.right() == area.right());
    let bottom = inset(tile.bottom() == area.bottom());
    let width = (tile.w - left - right).max(1);
    let height = (tile.h - top - bottom).max(1);
    Rect::new(tile.x + left, tile.y + top, width, height)
}

fn centered(width: i64, height: i64, area: Rect) -> Rect {
    Rect::new(
        area.x + (area.w - width) / 2,
        area.y + (area.h - height) / 2,
        width,
        height,
    )
}

/// The frame a layout gives `current` inside `area`; None for non-layout actions (restore, displays).
pub fn layout(name: &str, area: Rect, current: Rect, gap: i64) -> Option<Rect> {
    let col = |from: i64, to: i64| {
        let left = area.x + area.w * from / 6;
        Rect::new(left, area.y, area.x + area.w * to / 6 - left, area.h)
    };
    let half_w = area.w / 2;
    let half_h = area.h / 2;
    let tile = match name {
        "left-half" => Rect::new(area.x, area.y, half_w, area.h),
        "right-half" => Rect::new(area.x + half_w, area.y, area.w - half_w, area.h),
        "top-half" => Rect::new(area.x, area.y, area.w, half_h),
        "bottom-half" => Rect::new(area.x, area.y + half_h, area.w, area.h - half_h),
        "top-left" => Rect::new(area.x, area.y, half_w, half_h),
        "top-right" => Rect::new(area.x + half_w, area.y, area.w - half_w, half_h),
        "bottom-left" => Rect::new(area.x, area.y + half_h, half_w, area.h - half_h),
        "bottom-right" => Rect::new(
            area.x + half_w,
            area.y + half_h,
            area.w - half_w,
            area.h - half_h,
        ),
        "maximize" => area,
        "first-third" => col(0, 2),
        "center-third" => col(2, 4),
        "last-third" => col(4, 6),
        "first-two-thirds" => col(0, 4),
        "last-two-thirds" => col(2, 6),
        "center-half" => Rect::new(area.x + (area.w - half_w) / 2, area.y, half_w, area.h),
        "center" => {
            let width = current.w.min(area.w);
            let height = current.h.min(area.h);
            return Some(centered(width, height, area));
        }
        "almost-maximize" => {
            return Some(centered(area.w * 9 / 10, area.h * 9 / 10, area));
        }
        "maximize-height" => {
            return Some(Rect::new(current.x, area.y, current.w, area.h));
        }
        "larger" | "smaller" => {
            let step = if name == "larger" {
                RESIZE_STEP_PERCENT
            } else {
                -RESIZE_STEP_PERCENT
            };
            let min_w = area.w * MIN_WINDOW_PERCENT / 100;
            let min_h = area.h * MIN_WINDOW_PERCENT / 100;
            let width = (current.w + area.w * step * 2 / 100).clamp(min_w.min(current.w), area.w);
            let height = (current.h + area.h * step * 2 / 100).clamp(min_h.min(current.h), area.h);
            let x = (current.x - (width - current.w) / 2).clamp(area.x, area.right() - width);
            let y = (current.y - (height - current.h) / 2).clamp(area.y, area.bottom() - height);
            return Some(Rect::new(x, y, width, height));
        }
        "move-left" => return Some(Rect::new(area.x, current.y, current.w, current.h)),
        "move-right" => {
            return Some(Rect::new(
                area.right() - current.w,
                current.y,
                current.w,
                current.h,
            ));
        }
        "move-up" => return Some(Rect::new(current.x, area.y, current.w, current.h)),
        "move-down" => {
            return Some(Rect::new(
                current.x,
                area.bottom() - current.h,
                current.w,
                current.h,
            ));
        }
        _ => return None,
    };
    Some(if uses_gap(name) {
        apply_gap(tile, area, gap)
    } else {
        tile
    })
}

/// Screens ordered left to right, then top to bottom, like Rectangle's display cycling.
pub fn sort_screens(screens: &[Rect]) -> Vec<Rect> {
    let mut sorted: Vec<Rect> = screens.iter().copied().take(MAX_SCREENS).collect();
    sorted.sort_by_key(|screen| (screen.x, screen.y));
    sorted
}

/// Index of the screen holding most of the window, or the nearest one when it is off every screen.
pub fn screen_index(window: Rect, screens: &[Rect]) -> Option<usize> {
    let most_overlap = screens
        .iter()
        .enumerate()
        .map(|(index, screen)| (index, window.overlap_area(*screen)))
        .filter(|(_, overlap)| *overlap > 0)
        .max_by_key(|(_, overlap)| *overlap);
    if let Some((index, _)) = most_overlap {
        return Some(index);
    }
    let (cx, cy) = window.center();
    screens
        .iter()
        .enumerate()
        .min_by_key(|(_, screen)| {
            let (sx, sy) = screen.center();
            (cx - sx).abs() + (cy - sy).abs()
        })
        .map(|(index, _)| index)
}

/// Moves a window to another screen, keeping its position and size relative to the screen.
pub fn move_between_screens(window: Rect, from: Rect, to: Rect) -> Rect {
    let scale = |value: i64, source: i64, target: i64| {
        if source <= 0 {
            0
        } else {
            value * target / source
        }
    };
    let width = scale(window.w, from.w, to.w).clamp(1, to.w.max(1));
    let height = scale(window.h, from.h, to.h).clamp(1, to.h.max(1));
    let x = to.x + scale(window.x - from.x, from.w, to.w);
    let y = to.y + scale(window.y - from.y, from.h, to.h);
    Rect::new(
        x.clamp(to.x, (to.right() - width).max(to.x)),
        y.clamp(to.y, (to.bottom() - height).max(to.y)),
        width,
        height,
    )
}

/// The layout a dragged window snaps to when the cursor reaches a screen edge or corner.
pub fn cursor_snap_layout(
    cursor: (i64, i64),
    screen: Rect,
    edge: i64,
    corner: i64,
) -> Option<&'static str> {
    let (x, y) = cursor;
    if x < screen.x || y < screen.y || x >= screen.right() || y >= screen.bottom() {
        return None;
    }
    let near_left = x - screen.x < edge;
    let near_right = screen.right() - 1 - x < edge;
    let near_top = y - screen.y < edge;
    let near_bottom = screen.bottom() - 1 - y < edge;
    let corner_left = x - screen.x < corner;
    let corner_right = screen.right() - 1 - x < corner;
    let corner_top = y - screen.y < corner;
    let corner_bottom = screen.bottom() - 1 - y < corner;
    if !(near_left || near_right || near_top || near_bottom) {
        return None;
    }
    match (corner_left, corner_right, corner_top, corner_bottom) {
        (true, _, true, _) => Some("top-left"),
        (_, true, true, _) => Some("top-right"),
        (true, _, _, true) => Some("bottom-left"),
        (_, true, _, true) => Some("bottom-right"),
        _ if near_left => Some("left-half"),
        _ if near_right => Some("right-half"),
        _ if near_top => Some("maximize"),
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Applying layouts to the focused window
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FocusedWindow {
    pub pid: i32,
    pub bundle_id: String,
    pub frame: Rect,
    /// Visible area of each display (no menu bar or Dock).
    pub screens: Vec<Rect>,
    /// Full frame of each display, in the same order as `screens`.
    pub frames: Vec<Rect>,
    pub resizable: bool,
    pub fullscreen: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WindowError {
    NoAccessibility,
    NoWindow,
    Failed,
}

pub trait WindowBackend {
    fn focused(&mut self) -> Result<FocusedWindow, WindowError>;
    fn set_frame(&mut self, pid: i32, frame: Rect) -> Result<(), WindowError>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WindowOptions {
    pub gap: i64,
    pub skip_apps: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Outcome {
    Applied(Rect),
    Unchanged,
    Skipped,
    Refused(&'static str),
}

/// Remembers each window's frame from before our last move so Restore can undo it.
#[derive(Default)]
pub struct History {
    entries: HashMap<i32, (Rect, Rect)>,
    order: Vec<i32>,
}

impl History {
    fn remember(&mut self, pid: i32, original: Rect, applied: Rect) {
        if self.entries.insert(pid, (original, applied)).is_none() {
            self.order.push(pid);
            if self.order.len() > MAX_RESTORE_ENTRIES {
                let oldest = self.order.remove(0);
                self.entries.remove(&oldest);
            }
        }
    }

    fn forget(&mut self, pid: i32) {
        self.entries.remove(&pid);
        self.order.retain(|known| *known != pid);
    }
}

pub fn apply(
    history: &mut History,
    backend: &mut impl WindowBackend,
    layout_name: &str,
    options: &WindowOptions,
) -> Result<Outcome, WindowError> {
    let window = backend.focused()?;
    apply_to_window(history, backend, &window, layout_name, options, None)
}

/// Applies a layout to an already-read window. `area` picks the screen to lay out on (the one
/// under the cursor when dragging); otherwise the screen holding most of the window is used.
pub fn apply_to_window(
    history: &mut History,
    backend: &mut impl WindowBackend,
    window: &FocusedWindow,
    layout_name: &str,
    options: &WindowOptions,
    area: Option<Rect>,
) -> Result<Outcome, WindowError> {
    if options
        .skip_apps
        .iter()
        .any(|skipped| skipped.eq_ignore_ascii_case(&window.bundle_id))
    {
        return Ok(Outcome::Skipped);
    }
    if window.fullscreen {
        return Ok(Outcome::Refused(
            "Full-screen windows can't be moved. Exit full screen first.",
        ));
    }
    if !window.resizable && layout_name != "restore" {
        return Ok(Outcome::Refused(
            "This window can't be resized, so it was left alone.",
        ));
    }
    let screens = sort_screens(&window.screens);
    let preferred = area.and_then(|area| screens.iter().position(|screen| *screen == area));
    let Some(index) = preferred.or_else(|| screen_index(window.frame, &screens)) else {
        return Err(WindowError::NoWindow);
    };
    let target = match layout_name {
        "restore" => match history.entries.get(&window.pid) {
            Some((original, applied)) if *applied == window.frame => *original,
            _ => return Ok(Outcome::Unchanged),
        },
        "next-display" | "previous-display" => {
            if screens.len() < 2 {
                return Ok(Outcome::Refused("There is only one display."));
            }
            let count = screens.len();
            let next = if layout_name == "next-display" {
                (index + 1) % count
            } else {
                (index + count - 1) % count
            };
            move_between_screens(window.frame, screens[index], screens[next])
        }
        name => match layout(name, screens[index], window.frame, options.gap) {
            Some(frame) => frame,
            None => return Ok(Outcome::Unchanged),
        },
    };
    if target == window.frame {
        return Ok(Outcome::Unchanged);
    }
    let original = match history.entries.get(&window.pid) {
        Some((original, applied)) if *applied == window.frame => *original,
        _ => window.frame,
    };
    backend.set_frame(window.pid, target)?;
    if layout_name == "restore" {
        history.forget(window.pid);
    } else {
        history.remember(window.pid, original, target);
    }
    Ok(Outcome::Applied(target))
}

// ---------------------------------------------------------------------------
// Drag to edge
// ---------------------------------------------------------------------------

const DRAG_START_DISTANCE: i64 = 4;
const EDGE_ZONE: i64 = 5;
const CORNER_ZONE: i64 = 40;
const SIZE_TOLERANCE: i64 = 2;
/// Drag events to wait for the window to start following the cursor before treating the press as not a title-bar drag.
const DRAG_MOVE_RETRIES: u8 = 12;

/// What the snap preview overlay should do after a mouse event.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Preview {
    Unchanged,
    Show(Rect),
    Hide,
}

/// A layout chosen by a drag, and the display area it is laid out on.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DragDrop {
    pub window: FocusedWindow,
    pub layout: &'static str,
    pub area: Rect,
}

#[derive(Default)]
enum Phase {
    #[default]
    Idle,
    Pressed {
        origin: (i64, i64),
        window: Option<FocusedWindow>,
        attempts: u8,
    },
    Dragging {
        window: FocusedWindow,
        zone: Option<(&'static str, Rect)>,
    },
    Ignored,
}

/// Tells a title-bar drag from other mouse drags and tracks the edge zone under the cursor.
#[derive(Default)]
pub struct DragTracker {
    phase: Phase,
}

impl DragTracker {
    pub fn on_down(&mut self, cursor: (i64, i64), window: Option<FocusedWindow>) {
        self.phase = Phase::Pressed {
            origin: cursor,
            window,
            attempts: 0,
        };
    }

    pub fn on_move(
        &mut self,
        cursor: (i64, i64),
        read_window: &mut dyn FnMut() -> Option<FocusedWindow>,
        options: &WindowOptions,
    ) -> Preview {
        match &self.phase {
            Phase::Idle | Phase::Ignored => Preview::Unchanged,
            Phase::Pressed {
                origin,
                window,
                attempts,
            } => {
                let moved = (cursor.0 - origin.0).abs().max((cursor.1 - origin.1).abs());
                if moved < DRAG_START_DISTANCE {
                    return Preview::Unchanged;
                }
                let (origin, start, attempts) = (*origin, window.clone(), *attempts);
                self.phase = Phase::Ignored;
                let (Some(start), Some(now)) = (start, read_window()) else {
                    return Preview::Unchanged;
                };
                let same_size = (now.frame.w - start.frame.w).abs() <= SIZE_TOLERANCE
                    && (now.frame.h - start.frame.h).abs() <= SIZE_TOLERANCE;
                let not_moved_yet = (now.frame.x, now.frame.y) == (start.frame.x, start.frame.y);
                if now.pid == start.pid
                    && same_size
                    && not_moved_yet
                    && attempts < DRAG_MOVE_RETRIES
                {
                    // The window follows the cursor a moment later; look again on the next event.
                    self.phase = Phase::Pressed {
                        origin,
                        window: Some(start),
                        attempts: attempts + 1,
                    };
                    return Preview::Unchanged;
                }
                let dragged_by_title_bar = now.pid == start.pid && !not_moved_yet && same_size;
                let skipped = options
                    .skip_apps
                    .iter()
                    .any(|app| app.eq_ignore_ascii_case(&now.bundle_id));
                if !dragged_by_title_bar || skipped || !now.resizable || now.fullscreen {
                    return Preview::Unchanged;
                }
                self.phase = Phase::Dragging {
                    window: now,
                    zone: None,
                };
                self.on_move(cursor, read_window, options)
            }
            Phase::Dragging { window, zone } => {
                let next = Self::zone_at(cursor, window, options.gap);
                if next == *zone {
                    return Preview::Unchanged;
                }
                let preview = match next {
                    Some((layout_name, area)) => {
                        match layout(layout_name, area, window.frame, options.gap) {
                            Some(target) => Preview::Show(target),
                            None => Preview::Hide,
                        }
                    }
                    None => Preview::Hide,
                };
                if let Phase::Dragging { zone, .. } = &mut self.phase {
                    *zone = next;
                }
                preview
            }
        }
    }

    fn zone_at(
        cursor: (i64, i64),
        window: &FocusedWindow,
        _gap: i64,
    ) -> Option<(&'static str, Rect)> {
        if window.frames.len() != window.screens.len() {
            return None;
        }
        let index = window.frames.iter().position(|frame| {
            cursor.0 >= frame.x
                && cursor.0 < frame.right()
                && cursor.1 >= frame.y
                && cursor.1 < frame.bottom()
        })?;
        let frame = window.frames[index];
        let corner = CORNER_ZONE.min(frame.w / 6).min(frame.h / 6);
        cursor_snap_layout(cursor, frame, EDGE_ZONE, corner)
            .map(|name| (name, window.screens[index]))
    }

    /// Ends the drag; returns the layout to apply when the button was released in an edge zone.
    pub fn on_up(&mut self) -> Option<DragDrop> {
        match std::mem::take(&mut self.phase) {
            Phase::Dragging {
                window,
                zone: Some((layout, area)),
            } => Some(DragDrop {
                window,
                layout,
                area,
            }),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SCREEN: Rect = Rect::new(0, 25, 1200, 775);

    struct Fake {
        window: FocusedWindow,
        moves: Vec<(i32, Rect)>,
        fail: Option<WindowError>,
    }

    impl Fake {
        fn new(frame: Rect) -> Self {
            Self {
                window: FocusedWindow {
                    pid: 7,
                    bundle_id: "com.apple.Safari".into(),
                    frame,
                    screens: vec![SCREEN],
                    frames: vec![],
                    resizable: true,
                    fullscreen: false,
                },
                moves: Vec::new(),
                fail: None,
            }
        }
    }

    impl WindowBackend for Fake {
        fn focused(&mut self) -> Result<FocusedWindow, WindowError> {
            match self.fail {
                Some(error) => Err(error),
                None => Ok(self.window.clone()),
            }
        }
        fn set_frame(&mut self, pid: i32, frame: Rect) -> Result<(), WindowError> {
            self.moves.push((pid, frame));
            self.window.frame = frame;
            Ok(())
        }
    }

    fn run(fake: &mut Fake, history: &mut History, name: &str) -> Outcome {
        apply(history, fake, name, &WindowOptions::default()).unwrap()
    }

    #[test]
    fn halves_quarters_and_maximize_tile_the_visible_area() {
        let cur = Rect::new(100, 100, 400, 300);
        assert_eq!(
            layout("left-half", SCREEN, cur, 0),
            Some(Rect::new(0, 25, 600, 775))
        );
        assert_eq!(
            layout("right-half", SCREEN, cur, 0),
            Some(Rect::new(600, 25, 600, 775))
        );
        assert_eq!(
            layout("top-half", SCREEN, cur, 0),
            Some(Rect::new(0, 25, 1200, 387))
        );
        assert_eq!(
            layout("bottom-half", SCREEN, cur, 0),
            Some(Rect::new(0, 412, 1200, 388))
        );
        assert_eq!(
            layout("top-left", SCREEN, cur, 0),
            Some(Rect::new(0, 25, 600, 387))
        );
        assert_eq!(
            layout("bottom-right", SCREEN, cur, 0),
            Some(Rect::new(600, 412, 600, 388))
        );
        assert_eq!(layout("maximize", SCREEN, cur, 0), Some(SCREEN));
        assert_eq!(layout("restore", SCREEN, cur, 0), None);
        assert_eq!(layout("unknown", SCREEN, cur, 0), None);
    }

    #[test]
    fn thirds_cover_the_width_without_gaps_or_overlap() {
        let cur = Rect::new(0, 0, 10, 10);
        let area = Rect::new(10, 0, 1000, 600);
        let first = layout("first-third", area, cur, 0).unwrap();
        let center = layout("center-third", area, cur, 0).unwrap();
        let last = layout("last-third", area, cur, 0).unwrap();
        assert_eq!((first.x, center.x, last.x), (10, 343, 676));
        assert_eq!(first.x + first.w, center.x);
        assert_eq!(center.x + center.w, last.x);
        assert_eq!(last.x + last.w, 1010);
        let two_first = layout("first-two-thirds", area, cur, 0).unwrap();
        let two_last = layout("last-two-thirds", area, cur, 0).unwrap();
        assert_eq!((two_first.x, two_first.x + two_first.w), (10, 676));
        assert_eq!((two_last.x, two_last.x + two_last.w), (343, 1010));
    }

    #[test]
    fn center_keeps_size_and_oversized_windows_are_shrunk_to_fit() {
        assert_eq!(
            layout("center", SCREEN, Rect::new(0, 0, 400, 300), 0),
            Some(Rect::new(400, 262, 400, 300))
        );
        assert_eq!(
            layout("center", SCREEN, Rect::new(0, 0, 5000, 5000), 0),
            Some(SCREEN)
        );
        assert_eq!(
            layout("center-half", SCREEN, Rect::new(0, 0, 1, 1), 0),
            Some(Rect::new(300, 25, 600, 775))
        );
        assert_eq!(
            layout("almost-maximize", SCREEN, Rect::new(0, 0, 1, 1), 0),
            Some(Rect::new(60, 64, 1080, 697))
        );
        assert_eq!(
            layout("maximize-height", SCREEN, Rect::new(50, 100, 400, 300), 0),
            Some(Rect::new(50, 25, 400, 775))
        );
    }

    #[test]
    fn larger_and_smaller_resize_around_the_center_within_bounds() {
        let cur = Rect::new(300, 200, 600, 400);
        let larger = layout("larger", SCREEN, cur, 0).unwrap();
        assert_eq!((larger.w, larger.h), (720, 477));
        assert_eq!((larger.x, larger.y), (240, 162));
        let smaller = layout("smaller", SCREEN, cur, 0).unwrap();
        assert_eq!((smaller.w, smaller.h), (480, 323));
        let huge = layout("larger", SCREEN, SCREEN, 0).unwrap();
        assert_eq!(huge, SCREEN);
        let tiny = Rect::new(500, 300, 100, 100);
        let shrunk = layout("smaller", SCREEN, tiny, 0).unwrap();
        assert!(shrunk.w <= tiny.w && shrunk.w >= 1);
        let edge = layout("larger", SCREEN, Rect::new(0, 25, 600, 400), 0).unwrap();
        assert!(edge.x >= SCREEN.x && edge.x + edge.w <= SCREEN.x + SCREEN.w);
    }

    #[test]
    fn move_layouts_push_the_window_to_an_edge_keeping_its_size() {
        let cur = Rect::new(300, 200, 600, 400);
        assert_eq!(
            layout("move-left", SCREEN, cur, 0),
            Some(Rect::new(0, 200, 600, 400))
        );
        assert_eq!(
            layout("move-right", SCREEN, cur, 0),
            Some(Rect::new(600, 200, 600, 400))
        );
        assert_eq!(
            layout("move-up", SCREEN, cur, 0),
            Some(Rect::new(300, 25, 600, 400))
        );
        assert_eq!(
            layout("move-down", SCREEN, cur, 0),
            Some(Rect::new(300, 400, 600, 400))
        );
    }

    #[test]
    fn gap_insets_screen_edges_fully_and_shared_edges_by_half() {
        let cur = Rect::new(0, 0, 10, 10);
        assert_eq!(
            layout("left-half", SCREEN, cur, 10),
            Some(Rect::new(10, 35, 585, 755))
        );
        assert_eq!(
            layout("right-half", SCREEN, cur, 10),
            Some(Rect::new(605, 35, 585, 755))
        );
        assert_eq!(
            layout("maximize", SCREEN, cur, 10),
            Some(Rect::new(10, 35, 1180, 755))
        );
        assert_eq!(
            layout("center", SCREEN, Rect::new(0, 0, 400, 300), 10),
            Some(Rect::new(400, 262, 400, 300))
        );
        assert_eq!(
            layout("left-half", SCREEN, cur, -5),
            layout("left-half", SCREEN, cur, 0)
        );
        let tiny = layout("left-half", Rect::new(0, 0, 4, 4), cur, 50).unwrap();
        assert!(tiny.w >= 1 && tiny.h >= 1);
    }

    #[test]
    fn screens_sort_left_to_right_and_the_window_picks_the_screen_it_mostly_covers() {
        let left = Rect::new(0, 0, 1000, 800);
        let right = Rect::new(1000, 0, 1400, 900);
        let sorted = sort_screens(&[right, left]);
        assert_eq!(sorted, vec![left, right]);
        assert_eq!(
            screen_index(Rect::new(900, 100, 400, 300), &sorted),
            Some(1)
        );
        assert_eq!(
            screen_index(Rect::new(100, 100, 400, 300), &sorted),
            Some(0)
        );
        assert_eq!(
            screen_index(Rect::new(5000, 100, 400, 300), &sorted),
            Some(1)
        );
        assert_eq!(screen_index(Rect::new(0, 0, 1, 1), &[]), None);
        let many: Vec<Rect> = (0..40).map(|n| Rect::new(n * 10, 0, 10, 10)).collect();
        assert_eq!(sort_screens(&many).len(), MAX_SCREENS);
    }

    #[test]
    fn moving_between_screens_keeps_relative_position_and_fits_the_target() {
        let from = Rect::new(0, 0, 1000, 800);
        let to = Rect::new(1000, 0, 2000, 1600);
        assert_eq!(move_between_screens(from, from, to), to);
        let half = Rect::new(0, 0, 500, 800);
        assert_eq!(
            move_between_screens(half, from, to),
            Rect::new(1000, 0, 1000, 1600)
        );
        let small = Rect::new(1000, 100, 300, 200);
        let back = move_between_screens(small, to, from);
        assert_eq!(back, Rect::new(0, 50, 150, 100));
        assert_eq!(move_between_screens(half, Rect::new(0, 0, 0, 0), to).w, 1);
        let beyond = move_between_screens(Rect::new(-500, -500, 400, 300), from, to);
        assert!(beyond.x >= to.x && beyond.y >= to.y);
    }

    #[test]
    fn dragging_to_an_edge_or_corner_picks_a_snap_layout() {
        let screen = Rect::new(0, 0, 1000, 800);
        let zone = |x, y| cursor_snap_layout((x, y), screen, 5, 40);
        assert_eq!(zone(0, 400), Some("left-half"));
        assert_eq!(zone(999, 400), Some("right-half"));
        assert_eq!(zone(500, 0), Some("maximize"));
        assert_eq!(zone(500, 799), None);
        assert_eq!(zone(10, 0), Some("top-left"));
        assert_eq!(zone(990, 2), Some("top-right"));
        assert_eq!(zone(2, 790), Some("bottom-left"));
        assert_eq!(zone(997, 797), Some("bottom-right"));
        assert_eq!(zone(500, 400), None);
        assert_eq!(zone(6, 400), None);
        assert_eq!(zone(-1, 400), None);
        assert_eq!(zone(1000, 400), None);
    }

    #[test]
    fn names_map_to_actions_defaults_are_unique_and_known() {
        assert_eq!(action_name("left-half"), "window.left-half");
        assert_eq!(layout_of("window.left-half"), Some("left-half"));
        assert_eq!(layout_of("window.nope"), None);
        assert_eq!(layout_of("clipboard.history"), None);
        let mut seen = std::collections::HashSet::new();
        for (name, key, mask) in DEFAULT_SHORTCUTS {
            assert!(LAYOUTS.contains(name), "{name}");
            assert!(seen.insert((*key, *mask)), "duplicate default for {name}");
            assert!(*mask != 0 && *mask <= 0b1111);
        }
        let mut layouts = std::collections::HashSet::new();
        assert!(LAYOUTS.iter().all(|name| layouts.insert(*name)));
    }

    #[test]
    fn apply_moves_the_focused_window_and_restore_returns_it() {
        let original = Rect::new(100, 100, 400, 300);
        let mut fake = Fake::new(original);
        let mut history = History::default();
        assert_eq!(
            run(&mut fake, &mut history, "left-half"),
            Outcome::Applied(Rect::new(0, 25, 600, 775))
        );
        assert_eq!(
            run(&mut fake, &mut history, "left-half"),
            Outcome::Unchanged
        );
        assert_eq!(
            run(&mut fake, &mut history, "top-half"),
            Outcome::Applied(Rect::new(0, 25, 1200, 387))
        );
        assert_eq!(
            run(&mut fake, &mut history, "restore"),
            Outcome::Applied(original)
        );
        assert_eq!(fake.window.frame, original);
        assert_eq!(run(&mut fake, &mut history, "restore"), Outcome::Unchanged);
        assert_eq!(fake.moves.len(), 3);
    }

    #[test]
    fn restore_is_ignored_when_the_window_was_moved_by_someone_else() {
        let mut fake = Fake::new(Rect::new(100, 100, 400, 300));
        let mut history = History::default();
        run(&mut fake, &mut history, "left-half");
        fake.window.frame = Rect::new(5, 5, 300, 300);
        assert_eq!(run(&mut fake, &mut history, "restore"), Outcome::Unchanged);
        assert_eq!(fake.window.frame, Rect::new(5, 5, 300, 300));
    }

    #[test]
    fn display_moves_wrap_and_need_two_displays() {
        let second = Rect::new(1200, 0, 1000, 800);
        let mut fake = Fake::new(Rect::new(0, 25, 600, 775));
        let mut history = History::default();
        assert!(matches!(
            run(&mut fake, &mut history, "next-display"),
            Outcome::Refused(_)
        ));
        fake.window.screens = vec![second, SCREEN];
        assert!(
            matches!(run(&mut fake, &mut history, "next-display"), Outcome::Applied(frame) if frame.x >= 1200)
        );
        assert!(
            matches!(run(&mut fake, &mut history, "next-display"), Outcome::Applied(frame) if frame.x < 1200)
        );
        assert!(
            matches!(run(&mut fake, &mut history, "previous-display"), Outcome::Applied(frame) if frame.x >= 1200)
        );
    }

    #[test]
    fn skipped_fullscreen_and_fixed_size_windows_are_left_alone() {
        let mut history = History::default();
        let mut fake = Fake::new(Rect::new(100, 100, 400, 300));
        let skip = WindowOptions {
            gap: 0,
            skip_apps: vec!["COM.APPLE.SAFARI".into()],
        };
        assert_eq!(
            apply(&mut history, &mut fake, "left-half", &skip),
            Ok(Outcome::Skipped)
        );
        fake.window.fullscreen = true;
        assert!(matches!(
            run(&mut fake, &mut history, "left-half"),
            Outcome::Refused(_)
        ));
        fake.window.fullscreen = false;
        fake.window.resizable = false;
        assert!(matches!(
            run(&mut fake, &mut history, "left-half"),
            Outcome::Refused(_)
        ));
        assert!(fake.moves.is_empty());
    }

    #[test]
    fn backend_errors_and_missing_screens_are_reported() {
        let mut history = History::default();
        let mut fake = Fake::new(Rect::new(100, 100, 400, 300));
        fake.fail = Some(WindowError::NoAccessibility);
        assert_eq!(
            apply(
                &mut history,
                &mut fake,
                "left-half",
                &WindowOptions::default()
            ),
            Err(WindowError::NoAccessibility)
        );
        fake.fail = None;
        fake.window.screens.clear();
        assert_eq!(
            apply(
                &mut history,
                &mut fake,
                "left-half",
                &WindowOptions::default()
            ),
            Err(WindowError::NoWindow)
        );
    }

    #[test]
    fn history_is_bounded_and_forgets_the_oldest_window() {
        let mut history = History::default();
        for pid in 0..(MAX_RESTORE_ENTRIES as i32 + 5) {
            history.remember(pid, Rect::new(0, 0, 1, 1), Rect::new(1, 1, 1, 1));
        }
        assert_eq!(history.entries.len(), MAX_RESTORE_ENTRIES);
        assert!(!history.entries.contains_key(&0));
        assert!(history
            .entries
            .contains_key(&(MAX_RESTORE_ENTRIES as i32 + 4)));
    }

    fn drag_window(frame: Rect) -> FocusedWindow {
        FocusedWindow {
            pid: 7,
            bundle_id: "com.apple.Safari".into(),
            frame,
            screens: vec![Rect::new(0, 25, 1000, 775)],
            frames: vec![Rect::new(0, 0, 1000, 800)],
            resizable: true,
            fullscreen: false,
        }
    }

    #[test]
    fn a_title_bar_drag_to_the_left_edge_previews_then_drops_a_left_half() {
        let options = WindowOptions::default();
        let before = drag_window(Rect::new(300, 200, 400, 300));
        let mut tracker = DragTracker::default();
        tracker.on_down((400, 210), Some(before));
        let moved = drag_window(Rect::new(100, 150, 400, 300));
        assert_eq!(
            tracker.on_move((401, 211), &mut || panic!("too early"), &options),
            Preview::Unchanged
        );
        assert_eq!(
            tracker.on_move((200, 160), &mut || Some(moved.clone()), &options),
            Preview::Unchanged
        );
        assert_eq!(
            tracker.on_move((0, 400), &mut || panic!("window is read once"), &options),
            Preview::Show(Rect::new(0, 25, 500, 775))
        );
        assert_eq!(
            tracker.on_move((0, 410), &mut || panic!(), &options),
            Preview::Unchanged
        );
        assert_eq!(
            tracker.on_move((500, 400), &mut || panic!(), &options),
            Preview::Hide
        );
        assert_eq!(
            tracker.on_move((999, 400), &mut || panic!(), &options),
            Preview::Show(Rect::new(500, 25, 500, 775))
        );
        let drop = tracker.on_up().unwrap();
        assert_eq!(
            (drop.layout, drop.area),
            ("right-half", Rect::new(0, 25, 1000, 775))
        );
        assert_eq!(tracker.on_up(), None);
    }

    #[test]
    fn corners_and_top_edge_pick_quarters_and_maximize() {
        let options = WindowOptions::default();
        let mut tracker = DragTracker::default();
        tracker.on_down((10, 10), Some(drag_window(Rect::new(0, 0, 400, 300))));
        let moved = drag_window(Rect::new(50, 50, 400, 300));
        tracker.on_move((100, 100), &mut || Some(moved.clone()), &options);
        assert!(matches!(
            tracker.on_move((3, 2), &mut || None, &options),
            Preview::Show(_)
        ));
        assert_eq!(tracker.on_up().unwrap().layout, "top-left");
        tracker.on_down((10, 10), Some(drag_window(Rect::new(0, 0, 400, 300))));
        tracker.on_move((100, 100), &mut || Some(moved.clone()), &options);
        tracker.on_move((500, 1), &mut || None, &options);
        assert_eq!(tracker.on_up().unwrap().layout, "maximize");
    }

    #[test]
    fn drags_that_are_not_window_moves_are_ignored() {
        let options = WindowOptions::default();
        let start = drag_window(Rect::new(300, 200, 400, 300));
        let cases = [
            drag_window(Rect::new(100, 200, 600, 300)),
            FocusedWindow {
                pid: 8,
                ..drag_window(Rect::new(100, 150, 400, 300))
            },
            FocusedWindow {
                resizable: false,
                ..drag_window(Rect::new(100, 150, 400, 300))
            },
            FocusedWindow {
                fullscreen: true,
                ..drag_window(Rect::new(100, 150, 400, 300))
            },
        ];
        for now in cases {
            let mut tracker = DragTracker::default();
            tracker.on_down((400, 210), Some(start.clone()));
            assert_eq!(
                tracker.on_move((100, 100), &mut || Some(now.clone()), &options),
                Preview::Unchanged
            );
            assert_eq!(
                tracker.on_move((0, 400), &mut || panic!("ignored"), &options),
                Preview::Unchanged
            );
            assert_eq!(tracker.on_up(), None);
        }
        // A window that has not started to follow the cursor is re-read, then given up on.
        let mut tracker = DragTracker::default();
        tracker.on_down((400, 210), Some(start.clone()));
        for _ in 0..=DRAG_MOVE_RETRIES {
            assert_eq!(
                tracker.on_move((100, 100), &mut || Some(start.clone()), &options),
                Preview::Unchanged
            );
        }
        assert_eq!(
            tracker.on_move((0, 400), &mut || panic!("ignored"), &options),
            Preview::Unchanged
        );
        // ...but one that follows late still gets its preview.
        let mut tracker = DragTracker::default();
        tracker.on_down((400, 210), Some(start.clone()));
        assert_eq!(
            tracker.on_move((100, 100), &mut || Some(start.clone()), &options),
            Preview::Unchanged
        );
        let late = drag_window(Rect::new(100, 150, 400, 300));
        assert!(matches!(
            tracker.on_move((0, 400), &mut || Some(late.clone()), &options),
            Preview::Show(_)
        ));
        let mut tracker = DragTracker::default();
        tracker.on_down((400, 210), None);
        assert_eq!(
            tracker.on_move((100, 100), &mut || Some(start.clone()), &options),
            Preview::Unchanged
        );
        let mut idle = DragTracker::default();
        assert_eq!(
            idle.on_move((0, 0), &mut || panic!(), &options),
            Preview::Unchanged
        );
        let skip = WindowOptions {
            gap: 0,
            skip_apps: vec!["com.apple.safari".into()],
        };
        let mut tracker = DragTracker::default();
        tracker.on_down((400, 210), Some(start));
        let moved = drag_window(Rect::new(100, 150, 400, 300));
        assert_eq!(
            tracker.on_move((100, 100), &mut || Some(moved.clone()), &skip),
            Preview::Unchanged
        );
        assert_eq!(tracker.on_up(), None);
    }

    #[test]
    fn releasing_outside_an_edge_zone_or_without_matching_screens_does_nothing() {
        let options = WindowOptions::default();
        let start = drag_window(Rect::new(300, 200, 400, 300));
        let moved = drag_window(Rect::new(100, 150, 400, 300));
        let mut tracker = DragTracker::default();
        tracker.on_down((400, 210), Some(start.clone()));
        tracker.on_move((200, 200), &mut || Some(moved.clone()), &options);
        assert_eq!(tracker.on_up(), None);
        let mismatched = FocusedWindow {
            frames: vec![],
            ..moved
        };
        let mut tracker = DragTracker::default();
        tracker.on_down((400, 210), Some(start));
        tracker.on_move((200, 200), &mut || Some(mismatched.clone()), &options);
        assert_eq!(
            tracker.on_move((0, 400), &mut || None, &options),
            Preview::Unchanged
        );
        assert_eq!(tracker.on_up(), None);
    }

    #[test]
    fn dropping_applies_the_layout_on_the_display_under_the_cursor() {
        let second = Rect::new(1000, 25, 1000, 775);
        let mut fake = Fake::new(Rect::new(1100, 100, 400, 300));
        fake.window.screens = vec![SCREEN, second];
        let window = fake.window.clone();
        let mut history = History::default();
        let outcome = apply_to_window(
            &mut history,
            &mut fake,
            &window,
            "left-half",
            &WindowOptions::default(),
            Some(second),
        );
        assert_eq!(outcome, Ok(Outcome::Applied(Rect::new(1000, 25, 500, 775))));
    }
}
