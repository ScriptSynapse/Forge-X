from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, SelectMultipleField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

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
    limitations = TextAreaField("Limitations", filters=[strip], validators=[Optional(), Length(max=5000)])


class LinkEvidenceForm(FlaskForm):
    evidence_ids = SelectMultipleField("Add evidence", coerce=int, validators=[DataRequired("Choose evidence.")])


class CancelForm(FlaskForm):
    reason = TextAreaField("Reason for cancelling", filters=[strip],
                           validators=[DataRequired("Give a reason."), Length(min=5, max=500)])
