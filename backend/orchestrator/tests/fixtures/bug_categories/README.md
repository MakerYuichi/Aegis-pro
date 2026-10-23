# Bug categories

A test corpus organized by **class of bug**, not by project. Each subdirectory holds minimal, self-contained examples of one kind of bug — a buggy file and a fixed file that demonstrates the correct handling.

The pipeline is tested against this folder by `tests/test_bug_categories.py`. Every category has a `manifest.json` that declares what the pipeline should find (or not find) in that folder. The test reads every manifest, runs the scanner against the referenced files, and asserts the claims.

## Why categories, not repos

Testing against a single real repo proves the pipeline found *that one bug*. Testing against a category proves the pipeline finds *every bug of that shape*. As categories are added, the corpus becomes a regression suite: any change that breaks a category fails CI.

## Structure
bug_categories/
├── README.md ← this file
└── <category>/ ← e.g., null_handling
├── README.md ← what this category covers
└── NN_<subcategory>/ ← numbered subcategories
├── README.md
├── manifest.json
├── buggy_.py ← triggers the pattern
└── fixed_.py ← has the correct handling


## Adding a category

1. Create `bug_categories/<category>/<NN>_<subcategory>/`.
2. Write `buggy_*.py` and `fixed_*.py` files that are minimal reproductions of the shape.
3. Write `manifest.json` declaring the pattern and the expected line numbers, symbols, and terminal kinds.
4. Write `README.md` documenting the shape, why it's a bug, and what the fix looks like.
5. Flip `"covered": true` in the manifest when the pipeline actually finds it.
6. Run `pytest tests/test_bug_categories.py`.

## Current status

Categories are marked `covered: true` once the pipeline can reliably identify them. Until then, the test runner reports them as "known gaps" — visible, tracked, not silently ignored.

See `null_handling/README.md` for the category's current state.