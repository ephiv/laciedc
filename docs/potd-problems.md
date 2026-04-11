# Writing POTD Problems

Problems are stored as JSON files in `data/problems/*.json`.

## Problem Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier (e.g., `"sample_001"`) |
| `source` | string | Yes | Origin of the problem (e.g., `"AoPS"`, `"AMC 2023"`) |
| `type` | string | Yes | One of: `mcq`, `open`, `parts` |
| `problem` | string | Yes | The problem text |
| `answer` | string | Yes | Correct answer (case-insensitive) |
| `difficulty` | string | No | Difficulty rating (e.g., `"Easy"`, `"Medium"`, `"Hard"`) |
| `parts` | array | No | Required if `type` is `parts` |
| `options` | array | No | Required if `type` is `mcq` |
| `diagram` | object | No | For problems with diagrams |

## Problem Types

### Open Ended

```json
{
  "id": "sample_open_001",
  "source": "Custom",
  "type": "open",
  "problem": "What is the sum of the first 100 positive integers?",
  "answer": "5050",
  "difficulty": "Easy"
}
```

### Multiple Choice (MCQ)

```json
{
  "id": "sample_mcq_001",
  "source": "SAT Practice",
  "type": "mcq",
  "problem": "Which of the following is a prime number?",
  "answer": "B",
  "options": ["A. 4", "B. 7", "C. 9", "D. 15"],
  "difficulty": "Easy"
}
```

### Multi-Part

```json
{
  "id": "sample_parts_001",
  "source": "AMC 10",
  "type": "parts",
  "problem": "A rectangle has a perimeter of 20 cm.",
  "parts": [
    "What is the maximum possible area?",
    "What are the dimensions of the rectangle with maximum area?"
  ],
  "answer": "25",
  "difficulty": "Medium"
}
```

## Diagrams

The `type` field specifies the rendering method. Supported types:

### matplotlib

Custom matplotlib code:

```json
"diagram": {
  "type": "matplotlib",
  "code": "import numpy as np\ncircle = plt.Circle((0, 0), 5, fill=False)\nplt.gca().add_patch(circle)\nplt.gca().add_patch(plt.Rectangle((-3, -4), 6, 8, fill=False))\nplt.axis('equal')\nplt.xlim(-7, 7)\nplt.ylim(-7, 7)\nplt.title('Shaded Region Problem')"
}
```

Available in `code`: `plt`, `np` (numpy).

### latex

Render LaTeX expressions:

```json
"diagram": {
  "type": "latex",
  "code": r"$\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}$",
  "fontsize": 24
}
```

Optional: `width` (default 8), `height` (default 2), `fontsize` (default 20).

### image

Load from local file path (relative to `data/problems/` or absolute):

```json
"diagram": {
  "type": "image",
  "path": "diagrams/my_diagram.png"
}
```

### url

Download image from URL:

```json
"diagram": {
  "type": "url",
  "url": "https://example.com/diagram.png"
}
```

Requires internet connection when rendering.

## Adding Problems

1. Create a JSON file in `data/problems/`
2. Follow the schema above
3. The bot will auto-reload problems when the file is added/modified
4. Or use `/potd_add` to add via Discord

## Tips

- Keep problem text concise for best image rendering
- For long problems, they will wrap automatically
- Use `\n` in problem text for explicit line breaks
- Answers are case-insensitive when checked
