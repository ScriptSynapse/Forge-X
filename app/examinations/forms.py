from flask_wtf import FlaskForm
from wtforms import DateField, HiddenField, SelectField, SelectMultipleField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from ..auth.forms import strip


class CreateExamForm(FlaskForm):
    case_id = SelectField("Case", coerce=int, validators=[DataRequired("Choose a case.")])
    examination_type_id = SelectField("Examination type", coerce=int, validators=[DataRequired("Choose a type.")])
    examiner_id = SelectField("Examiner", coerce=int, validators=[DataRequired("Choose the examiner.")])
    due_date = DateField("Due date", validators=[Optional()])
    evidence_ids = SelectMultipleField("Evidence to examine", coerce=int, validators=[Optional()])


class ExamRecordForm(FlaskForm):
    tools_methods = TextAreaField("Tools and methods", filters=[strip], validators=[Optional(), Length(max=5000)])
    observations = TextAreaField("Observations", filters=[strip], validators=[Optional(), Length(max=10000)])
    findings = TextAreaField("Findings", filters=[strip], validators=[Optional(), Length(max=10000)])
    conclusion = TextAreaField("Conclusion", filters=[strip], validators=[Optional(), Length(max=10000)])
    limitations = TextAreaField("Limitations", filters=[strip], validators=[Optional(), Length(max=5000)])


class LinkEvidenceForm(FlaskForm):
    evidence_ids = SelectMultipleField("Add evidence", coerce=int, validators=[DataRequired("Choose evidence.")])


class CancelForm(FlaskForm):
    reason = TextAreaField("Reason for cancelling", filters=[strip],
                           validators=[DataRequired("Give a reason."), Length(min=5, max=500)])


class ArtifactForm(FlaskForm):
    """An artifact found during the examination (append-only)."""
    artifact_type = SelectField("Type")
    description = StringField("Description", filters=[strip],
                              validators=[DataRequired("Describe the artifact."), Length(min=2, max=500)])
    location = StringField("Where it was found", filters=[strip], validators=[Optional(), Length(max=500)])
    evidence_id = SelectField("From evidence item", coerce=int)
    sha256 = StringField("SHA-256 (optional)", filters=[lambda v: (v or "").strip().lower() or None], validators=[Optional()])
    corrects_artifact_id = HiddenField()

    def validate_sha256(self, field):
        import re
        if field.data and not re.fullmatch(r"[0-9a-f]{64}", field.data):
            raise ValidationError("A SHA-256 is exactly 64 characters, using 0–9 and a–f.")


class ReviewForm(FlaskForm):
    note = TextAreaField("Review note", filters=[strip], validators=[Optional(), Length(max=500)])
