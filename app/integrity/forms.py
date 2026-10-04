"""One form for the three hash actions: record, verify and correct."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import RadioField, StringField, TextAreaField
from wtforms.validators import Length, Optional

from ..auth.forms import strip
from ..evidence.services import is_valid_sha256, normalise_hash

METHODS = [("sample", "Compute it from a sample file"),
           ("manual", "Enter a hash calculated elsewhere")]


class HashForm(FlaskForm):
    method = RadioField("How do you want to provide the hash?", choices=METHODS, default="sample")
    sample_file = FileField("Sample file")
    hash_value = StringField("SHA-256", filters=[normalise_hash], validators=[Optional()])
    notes = StringField("Notes", filters=[strip], validators=[Optional(), Length(max=500)])
    reason = TextAreaField("Reason for the correction", filters=[strip], validators=[Optional(), Length(max=500)])

    def __init__(self, mode, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode          # "record", "verify" or "correct"

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if self.method.data == "sample":
            upload = self.sample_file.data
            if not upload or not getattr(upload, "filename", ""):
                self.sample_file.errors.append("Choose a sample file.")
                ok = False
        else:
            if not is_valid_sha256(self.hash_value.data):
                self.hash_value.errors.append("A SHA-256 hash is exactly 64 characters, using 0–9 and a–f.")
                ok = False
            if not self.notes.data:
                self.notes.errors.append("Say where this hash came from, e.g. the tool and its report.")
                ok = False
        if self.mode == "correct" and (not self.reason.data or len(self.reason.data) < 10):
            self.reason.errors.append("Explain what was wrong with the recorded hash (at least 10 characters).")
            ok = False
        return ok
