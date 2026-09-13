# Matching Icon SVG

## Task

Create an editable SVG that matches the artwork in
[Icon.ico](../src/main/icons/Icon.ico) as closely as practical.

## Scope

- Add [Icon.svg](../src/main/icons/Icon.svg) beside the existing ICO.
- Preserve the original ICO and all build/runtime references.
- Reproduce geometry, colors, transparency, and rounded edges with vector shapes.
- Exclude application behavior, packaging changes, and unrelated asset changes.

## Design

Use the largest ICO frame, 256x256, as the visual reference. Sample its solid
colors and edge positions, then reconstruct the background, circles, panels, and
bars as SVG primitives. Fit fractional coordinates with SciPy against Qt SVG
renders and round coordinates to three decimal places. SciPy is only a local
design tool, not an application or SVG dependency.

The SVG is a standalone asset with no external resources, scripts, or embedded
bitmap. Threading, persistence, and runtime failure handling are not applicable
because the application continues using the unchanged ICO. Different SVG
rasterizers may produce slightly different antialiasing at shape boundaries.

## Alternatives

- Embed the original PNG: exact pixels, but not editable vector artwork.
- Automatic tracing: unnecessary path complexity for simple geometric shapes.
- Selected: hand-reconstruct the geometry and use raster comparison to refine it.

## Runtime Effects

No startup, steady-state CPU/memory, I/O, background jobs, or process changes.
No cancellation is needed. The application does not load this new asset.

## Tests

- Parse the SVG as XML; check viewBox, palette, and standalone vector elements.
- Rasterize at 16, 24, 32, 48, 64, 128, 256, and 1024 pixels with Qt SVG.
- Compare against the largest ICO frame: premultiplied RGBA mean absolute error
  below 0.15/255, exact pixel agreement above 97.5%, alpha error below 0.1/255.
- Inspect the reference and render visually, including at enlarged size.
- Run `git diff --check` and
  `git diff --exit-code -- src/main/icons/Icon.ico`.
- Unit/integration/application performance tests: not applicable to an unused
  static artwork asset. The focused executable regression checks are below.
- README changes: not applicable; no application commands, setup, or workflows
  change. Do not run the complete application suite.

## Implementation Steps

1. Decode the largest ICO frame and measure its shapes and colors. Completed.
2. Create the SVG and immediately validate its XML and raster rendering. Completed.
3. Refine visible differences and repeat the focused comparison. Completed.
4. Record results, update the changelog, and move this task to Done. Completed.

## Acceptance Criteria

- A standalone, editable vector SVG exists beside the original ICO.
- Its artwork closely matches the reference, with remaining differences
  described by the validation results.
- The ICO and application behavior are unchanged.
- The task index and changelog record completion.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Reviewed the geometric reconstruction approach and testable acceptance
  criteria; retain the ICO unchanged and validate the SVG against its largest frame.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Created a vector-only SVG with the six sampled colors and fitted
  geometry. Qt rendering and pixel-comparison checks passed at eight sizes.

## Validation Results

- Initial XML/render check passed immediately after the SVG was created:
  mean absolute error 0.2582/255 and 97.56% exact pixels.
- Final comparison passed: premultiplied RGBA mean absolute error 0.06995/255,
  97.687% exact pixels, and alpha mean absolute error 0.03772/255. Transparent
  pixels' invisible RGB values are excluded by premultiplication.
- One intermediate check incorrectly expected the narrow panel gap to remain a
  pure background pixel at 16px. Sampling the bottom-center background instead
  corrected that test assumption; all eight render sizes passed afterward.
- Visually inspected the ICO preview, native 256px reference, initial 256px SVG
  render, and final 1024px render. Geometry and palette match closely; residual
  edge differences mean the result is not claimed to be pixel-identical.
- VS Code reported no SVG diagnostics. `git diff --check` and the unchanged-ICO
  check passed. The task/index links were checked for existing targets.
- Browser-specific rasterization was not tested. No runtime or full-suite tests
  were needed; application behavior and existing asset references are unchanged.

Exact focused regression command, run from the repository root in PowerShell
with the existing PyQt5 environment; generated previews stay in the system temp
directory:

```powershell
@'
import os
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtSvg import QSvgRenderer
path = Path('src/main/icons/Icon.svg')
root = ET.parse(path).getroot()
assert root.attrib['viewBox'] == '0 0 256 256'
assert all(element.tag.split('}')[-1] in {'svg', 'rect', 'circle', 'g'} for element in root.iter())
assert all(not any(token in name.lower() for token in ('href', 'style', 'onload')) for element in root.iter() for name in element.attrib)
assert {element.attrib['fill'] for element in root.iter() if 'fill' in element.attrib} == {'#3c3a2d', '#ed253e', '#f68f33', '#72be44', '#ffffff', '#f5e1d8'}
data = path.with_suffix('.ico').read_bytes()
frames = [struct.unpack_from('<BBBBHHII', data, 6 + index * 16) for index in range(struct.unpack_from('<H', data, 4)[0])]
frame = max(frames, key=lambda entry: (entry[0] or 256) * (entry[1] or 256))
reference = QImage.fromData(data[frame[7]:frame[7]+frame[6]])
assert reference.width() == reference.height() == 256
renderer = QSvgRenderer(str(path))
assert renderer.isValid()
for size in (16,24,32,48,64,128,256,1024):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    assert image.pixelColor(size // 2, size - 1).getRgb() == (60,58,45,255)
    if size in (256,1024):
        assert image.save(os.path.join(os.environ['TEMP'], f'RoyiFileManager-Icon-svg-{size}.png'))
    if size != 256:
        continue
    error = exact = alpha_error = 0
    for row in range(size):
        for column in range(size):
            actual = image.pixelColor(column, row).getRgb()
            expected = reference.pixelColor(column, row).getRgb()
            alpha_error += abs(actual[3] - expected[3])
            actual = tuple(round(value * actual[3] / 255) for value in actual[:3]) + (actual[3],)
            expected = tuple(round(value * expected[3] / 255) for value in expected[:3]) + (expected[3],)
            error += sum(abs(left - right) for left, right in zip(actual, expected))
            exact += actual == expected
    mae = error / (size * size * 4)
    assert mae < 0.15, mae
    assert exact / (size * size) > 0.975
    assert alpha_error / (size * size) < 0.1
    print(f'256px: premultiplied RGBA MAE={mae:.5f}/255; exact pixels={exact / (size * size):.3%}; alpha MAE={alpha_error / (size * size):.5f}/255')
print('PASS: XML, palette, vector-only structure, reference comparison, and rendering at 16/24/32/48/64/128/256/1024px')
'@ | python -
```