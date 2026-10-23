"""
Makes the local model's replies sound like a person on the phone.

A 4B model asked in the prompt to "talk naturally" gets worse at tool calls
(see the persona notes in ollama_harness.py). So the prompt stays short and
this module rewrites the habits that make the model sound like an assistant,
in code:

- "₹220" becomes "220 rupees", which the voice can say.
- An opener such as "Great!" or "Thank you, Anas!" starts at most every other
  reply, instead of every reply.
- Stock assistant phrases get plainer words: "Could you please provide" →
  "Can you tell me", "I'm sorry, but" → "Sorry,".
- A reply has at most one "!", so the voice does not sound overexcited.
- A statement said in the previous reply is not said again word for word,
  for example the starters after the customer only says "yeah". Questions stay.

The text is rewritten a sentence at a time. A long sentence goes out at a
clause end, at the same length as utils.split_speakable, so the voice can
start early. A clause that ends in "sorry," waits for its "but".
"""

import re

from utils import CLAUSE_END, MIN_CLAUSE_CHARS, SENTENCE_END

# A clause end that splits a phrase in PHRASES
SPLITS_PHRASE = re.compile(r"\b(sorry|apologi[sz]e),\s*$", re.IGNORECASE)

RUPEES = re.compile(r"₹\s*(\d[\d,]*\d|\d)")

# A sentence that is only a filler opener: "Great!", "Sure, Anas!"
OPENER = re.compile(
    r"^(great|sure|perfect|thank you|thanks|okay|alright|got it|"
    r"i understand|no problem|of course|wonderful|excellent)"
    r"(,\s*[A-Z][\w ]{0,20})?\s*[!.]$",
    re.IGNORECASE,
)


def _sorry(match: re.Match) -> str:
    """'Sorry, ' at the start of a sentence, 'sorry, ' after 'Oh, '."""
    starts = not match.string[: match.start()].strip()
    return "Sorry, " if starts else "sorry, "


# (pattern, replacement), applied in order to each part
PHRASES = [
    (r"\bI[’']m sorry, but\s+", _sorry),
    (r"\bI apologi[sz]e, but\s+", _sorry),
    (r"\bCould you please provide( me with)?\b", "Can you tell me"),
    (r"\bCould you please\b", "Can you"),
    (r"\bWould you like to add anything else to your order\?", "Anything else?"),
    (
        r"\bIs there anything else I can help you with( today)?\?",
        "Anything else I can do for you?",
    ),
    (r"\brepeat it again\b", "say it again"),
    (r"\bplease provide\b", "please tell me"),
    (r"\bCredit Card\b", "credit card"),
]
PHRASES = [(re.compile(p, re.IGNORECASE), r) for p, r in PHRASES]

SENTENCES = re.compile(r"[^.!?]+[.!?]*\s*")


def say_rupees(text: str) -> str:
    """'₹220' → '220 rupees'."""
    return RUPEES.sub(r"\1 rupees", text)


class SpeechStyle:
    """
    Rewrites one conversation's replies as they stream. Call start() before
    each reply, feed() with each chunk, then flush() at the end.
    """

    def __init__(self):
        self.last_had_opener = False
        self.pending = ""
        self.first_part = True
        self.exclaimed = False
        self.opener_now = False
        self.dropped = ""
        self.spoke = False
        # Sentences of the previous reply and of this one, normalized
        self.previous: set[str] = set()
        self.said: set[str] = set()

    def start(self) -> None:
        self.pending = ""
        self.first_part = True
        self.exclaimed = False
        self.opener_now = False
        self.dropped = ""
        self.spoke = False
        self.said = set()

    def feed(self, chunk: str) -> str:
        text = self.pending + chunk
        match = SENTENCE_END.match(text)
        if not match and len(text) >= MIN_CLAUSE_CHARS:
            match = CLAUSE_END.match(text)
            if match and SPLITS_PHRASE.search(match.group(0)):
                match = None
        if not match:
            self.pending = text
            return ""
        self.pending = text[match.end() :]
        return self._rewrite(match.group(0))

    def flush(self) -> str:
        """The rest of the reply. Also records whether it had an opener."""
        rest, self.pending = self.pending, ""
        out = self._rewrite(rest) if rest.strip() else ""
        if not self.spoke and self.dropped:
            # Everything was dropped: say the first part after all
            out, self.opener_now = self.dropped, True
        if self.spoke or out:
            # A request that only called tools says nothing, and keeps the state
            self.last_had_opener = self.opener_now
            self.previous = self.said
        return out

    def _rewrite(self, text: str) -> str:
        out = ""
        for sentence in SENTENCES.findall(say_rupees(text)):
            stripped = sentence.strip()
            if self.first_part and OPENER.match(stripped):
                self.first_part = False
                if self.last_had_opener:
                    # Two replies in a row would open the same way: drop it
                    self.dropped = sentence
                    continue
                self.opener_now = True
            elif stripped:
                self.first_part = False
            for pattern, replacement in PHRASES:
                sentence = pattern.sub(replacement, sentence)
            key = re.sub(r"[^a-z0-9 ]", "", stripped.lower())
            if key in self.previous and not stripped.endswith("?") and len(key) > 15:
                self.dropped = self.dropped or sentence
                continue
            self.said.add(key)
            if "!" in sentence:
                if self.exclaimed:
                    sentence = sentence.replace("!", ".")
                self.exclaimed = True
            out += sentence
        self.spoke = self.spoke or bool(out.strip())
        return out
