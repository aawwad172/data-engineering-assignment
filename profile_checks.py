"""Checks for the profiling exercises in profile.ipynb (assignment steps 4a-4e).

SPOILER WARNING: this file computes the correct answers (from data/articles.csv,
not from MongoDB). Don't read it until you've finished the exercises.

Each check prints one line per item:  ✅ correct  or  ❌ what is wrong.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from typing import Any

import pandas as pd

from collect import CSV_PATH


# ---------------------------------------------------------------------------
# The expected answers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _expected_words() -> tuple[str, ...]:
    summaries = pd.read_csv(CSV_PATH)["summary"]
    return tuple(word for text in summaries for word in re.findall(r"[a-z]+", text.lower()))


@lru_cache(maxsize=1)
def _expected_counts() -> Counter:
    return Counter(_expected_words())


@lru_cache(maxsize=1)
def _stopwords() -> frozenset[str]:
    import nltk
    from nltk.corpus import stopwords

    nltk.download("stopwords", quiet=True)
    return frozenset(stopwords.words("english"))


@lru_cache(maxsize=1)
def _expected_misspelled() -> frozenset[str]:
    from spellchecker import SpellChecker

    return frozenset(SpellChecker().unknown(set(_expected_counts())))


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------


class _Report:
    def __init__(self, step: str) -> None:
        self.step = step
        self.lines: list[str] = []
        self.ok = True

    def item(self, name: str, passed: bool, problem: str = "") -> None:
        self.ok &= passed
        self.lines.append(f"  {'✅' if passed else '❌'} {name}" + ("" if passed else f": {problem}"))

    def show(self) -> bool:
        print(f"Step {self.step}")
        print("\n".join(self.lines))
        print("  🎉 All correct!" if self.ok else "  Keep going.")
        return self.ok


def _check_top_pairs(report: _Report, name: str, actual: Any, true_counts: Counter, n: int = 10) -> None:
    """Check a list of (word, count) pairs: n items, biggest first, correct counts, really the top n."""
    try:
        pairs = [(str(word), int(count)) for word, count in actual]
    except (TypeError, ValueError):
        report.item(name, False, "should be a list of (word, count) pairs")
        return
    counts = [count for _, count in pairs]
    if len(pairs) != n:
        report.item(name, False, f"should have {n} items, got {len(pairs)}")
    elif counts != sorted(counts, reverse=True):
        report.item(name, False, "should be sorted from most to least frequent")
    elif any(true_counts.get(word) != count for word, count in pairs):
        report.item(name, False, "some counts don't match their word")
    elif counts != [count for _, count in true_counts.most_common(n)]:
        report.item(name, False, f"these aren't the {n} most frequent")
    else:
        report.item(name, True)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_4a(words: Any) -> bool:
    r = _Report("4a - Split the text into words")
    if not isinstance(words, list):
        r.item("words", False, f"should be a list, got {type(words).__name__}")
        return r.show()

    expected = _expected_counts()
    not_strings = [w for w in words if not isinstance(w, str)]
    if not_strings:
        r.item(
            "every item is a word (str)",
            False,
            f"found {len(not_strings):,} items that are {type(not_strings[0]).__name__}, "
            f"e.g. {str(not_strings[0])[:60]}. Is it a list of lists?",
        )
        return r.show()
    bad = [w for w in words if not re.fullmatch(r"[a-z]+", w)]
    r.item("only lowercase a-z words", not bad, f"found e.g. {bad[:5]}")
    r.item("total number of words", len(words) == sum(expected.values()), f"got {len(words):,}")
    r.item("number of different words", len(set(words)) == len(expected), f"got {len(set(words)):,}")
    if r.ok:
        r.item("every word counted the same number of times", Counter(words) == expected, "some counts differ")
    return r.show()


def check_4b(top_10_words: Any) -> bool:
    r = _Report("4b - 10 most frequent words")
    _check_top_pairs(r, "top_10_words", top_10_words, _expected_counts())
    return r.show()


def check_4d(total_stopwords: Any, top_10_stopwords: Any) -> bool:
    r = _Report("4d - Stopwords")
    stop = _stopwords()
    stop_counts = Counter({w: c for w, c in _expected_counts().items() if w in stop})
    expected_total = sum(stop_counts.values())
    r.item("total_stopwords", total_stopwords == expected_total, f"got {total_stopwords}")
    _check_top_pairs(r, "top_10_stopwords", top_10_stopwords, stop_counts)
    return r.show()


def check_4e(misspelled_words: Any, top_10_misspelled: Any) -> bool:
    r = _Report("4e - Spelling mistakes")
    expected = _expected_misspelled()
    if not isinstance(misspelled_words, (set, frozenset, list, tuple)):
        r.item("misspelled_words", False, f"should be a set, got {type(misspelled_words).__name__}")
    else:
        got = set(misspelled_words)
        r.item(
            "misspelled_words",
            got == expected,
            f"got {len(got):,} words; {len(got - expected):,} shouldn't be there, {len(expected - got):,} are missing",
        )
    misspelled_counts = Counter({w: c for w, c in _expected_counts().items() if w in expected})
    _check_top_pairs(r, "top_10_misspelled", top_10_misspelled, misspelled_counts)
    return r.show()
