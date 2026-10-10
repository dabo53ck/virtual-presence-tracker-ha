# Contributing

Bug reports and questions go to the
[GitHub issues](https://github.com/dabo53ck/virtual-presence-tracker-ha/issues).

## Adding a translation

The integration speaks English, German, French and Spanish. A new language
needs two changes, both in `custom_components/virtual_presence_tracker/`.

1. **What Home Assistant shows** (forms, entity names, repair issues, actions):
   copy `translations/en.json` to `translations/<code>.json`, where `<code>` is
   the language code Home Assistant uses (`nl`, `it`, `lb`, …), and translate
   the values. Leave every key exactly as it is.
2. **The phone messages** (the prompt, the reminder, the question about a
   device left behind and the notes about an unanswered question): these are
   sent by the integration itself and live in `messages.py`, in the `_TEXTS`
   dictionary. Add a block for your language with the same keys as the `"en"`
   block. Until a language is there, its messages are sent in English.

Please also add your language code to the list in
`tests/test_translations.py` (`test_a_translation_has_every_key`), which checks
that a translation has exactly the keys of the English file.

## English is the source of truth

English lives in two files, `strings.json` and `translations/en.json`, and they
must stay **byte-identical**; a test checks this. Change an English string in
both files at once. A translation never touches either of them.

## Checks

`ruff check .`, `ruff format --check .` and `pytest` have to pass. CI runs
them, plus hassfest and the HACS validation, on every pull request.

To run the tests yourself, use Python 3.14, install the test tools with
`pip install -r requirements-test.txt` and run `pytest`. CI on Linux is the
result that counts.
