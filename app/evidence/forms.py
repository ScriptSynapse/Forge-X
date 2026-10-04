"""Evidence forms (Flask-WTF adds a CSRF token to each)."""
from flask_wtf import FlaskForm
from wtforms import DateTimeLocalField, HiddenField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

from ..auth.forms import strip
from .services import HASH_SOURCES, is_valid_sha256, normalise_hash


class EvidenceDetailsMixin:
    description = TextAreaField("Description", filters=[strip],
                                validators=[DataRequired("Describe the item."), Length(min=5, max=500)])
    source_details = StringField("Source details", filters=[strip], validators=[Optional(), Length(max=255)])
    size_bytes = IntegerField("Size in bytes", validators=[Optional(), NumberRange(min=0, max=10**18,
                                                                                    message="Enter a whole number of bytes.")])
    collection_site = StringField("Collection site", filters=[strip],
                                  validators=[DataRequired("Where was it collected?"), Length(min=2, max=200)])


class RegisterEvidenceForm(EvidenceDetailsMixin, FlaskForm):
    case_id = SelectField("Case", coerce=int, validators=[DataRequired("Choose a case.")])
    evidence_type_id = SelectField("Evidence type", coerce=int, validators=[DataRequired("Choose a type.")])
    collected_at = DateTimeLocalField("Collected at", format="%Y-%m-%dT%H:%M",
                                      validators=[DataRequired("Enter the collection date and time.")])
    collected_by = SelectField("Collected by", coerce=int, validators=[DataRequired("Choose who collected it.")])
    collection_condition = StringField("Condition at collection", filters=[strip],
                                       validators=[DataRequired("Describe its condition, e.g. Sealed, intact."),
                                                   Length(min=2, max=200)])
    seal_number = StringField("Seal number", filters=[strip], validators=[Optional(), Length(max=30)])
    original_hash = StringField("Original SHA-256", filters=[normalise_hash], validators=[Optional()])
    hash_source = SelectField("How was this hash obtained?", choices=list(HASH_SOURCES), default="Computed")
    hash_notes = StringField("Hash notes", filters=[strip], validators=[Optional(), Length(max=500)])

    def validate_original_hash(self, field):
        if field.data and not is_valid_sha256(field.data):
            raise ValidationError("A SHA-256 hash is exactly 64 characters, using 0–9 and a–f.")

    def validate(self, extra_validators=None):
        """Cross-field rule. It lives here, not in validate_hash_notes, because
        WTForms skips a field's own checks when Optional() finds it empty."""
        ok = super().validate(extra_validators=extra_validators)
        if self.original_hash.data and self.hash_source.data == "Manual" and not self.hash_notes.data:
            self.hash_notes.errors.append("Say where this hash was copied from, e.g. the acquisition log.")
            ok = False
        return ok


class EditEvidenceForm(EvidenceDetailsMixin, FlaskForm):
    version = HiddenField()
