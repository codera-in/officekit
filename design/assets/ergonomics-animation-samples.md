# Ergonomics animation samples

Version: 1.0.0 · 2026-10-21 · Design prototypes, not production animation.

The character identity was accepted by the owner. These samples respond to the request for actual water cap-opening/drinking/recapping, stretching, eye-rest motion, and configurable placement in all four corners.

## Files

| Sample | Generated pose sheet | Playable export |
| --- | --- | --- |
| Water | ergonomics-water-animation-v1.png | ergonomics-water-animation-v1.gif |
| Stretch | ergonomics-stretch-animation-v1.png | ergonomics-stretch-animation-v1.gif |
| Eye rest | ergonomics-eyes-animation-v1.png | ergonomics-eyes-animation-v1.gif |

Each sheet was generated with built-in imagegen; its sibling Markdown file records the exact prompt. FFmpeg assembles the generated cells into a 256×256 looping GIF, 16 frames at 4 fps, using `scripts/ergonomics-animation-samples.mjs`. This is a stop-motion action prototype. Poses vary slightly in scale and anatomy between frames; smooth rigged animation and consistent final art remain production requirements. A first water sheet with an extra raised arm was discarded; the retained sheet corrects that artifact.

## Interactive preview

`design/mocks/ergonomics-animation.html` plays the generated sheets on canvas. Select water/stretch/eye rest, all four corners, pause/play, reduced motion and light/dark. The companion and prompt are anchored together inside a simulated desktop. No native permissions, sensor stream or actual reminder schedule runs.

## Browser checks

Opened and visually inspected in a new Superset Browser tab for this workspace. `scripts/ergonomics-animation-check.mjs` verifies advancing frames for each sample, all four corner placements fully inside their scene at 1280px and 390px, no horizontal overflow, and a static frame when reduced motion is enabled. All pass. The dark water sample was visually inspected. FFprobe confirms the water GIF has 16 frames, 4 seconds and 256×256 dimensions. This evidence covers the browser mock only, not native desktop placement, production timing, hardware or packaging.
