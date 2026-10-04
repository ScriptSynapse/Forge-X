from flask_wtf import FlaskForm
from wtforms import SelectField, SelectMultipleField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from ..auth.forms import strip


class ReportContentMixin:
    methodology = TextAreaField("Methodology", filters=[strip], validators=[Optional(), Length(max=20000)])
    observations = TextAreaField("Observations", filters=[strip], validators=[Optional(), Length(max=20000)])
    findings = TextAreaField("Findings", filters=[strip], validators=[Optional(), Length(max=20000)])
    conclusions = TextAreaField("Conclusions", filters=[strip], validators=[Optional(), Length(max=20000)])
    limitations = TextAreaField("Limitations", filters=[strip], validators=[Optional(), Length(max=20000)])

    def sections(self):
        return {k: self[k].data or None for k in ("methodology", "observations", "findings", "conclusions", "limitations")}


class CreateReportForm(ReportContentMixin, FlaskForm):
    case_id = SelectField("Case", coerce=int, validators=[DataRequired("Choose a case.")])
    title = StringField("Title", filters=[strip], validators=[DataRequired("Give the report a title."), Length(min=4, max=200)])
    examination_ids = SelectMultipleField("Examinations cited", coerce=int, validators=[Optional()])


class VersionForm(ReportContentMixin, FlaskForm):
    change_note = StringField("What changed in this version?", filters=[strip],
                              validators=[DataRequired("Describe the change."), Length(min=3, max=255)])


class LinkExamsForm(FlaskForm):
    examination_ids = SelectMultipleField("Cite examinations", coerce=int, validators=[DataRequired("Choose examinations.")])


class ReturnForm(FlaskForm):
    note = TextAreaField("What should the author change?", filters=[strip],
                         validators=[DataRequired("Explain what to change."), Length(min=5, max=500)])
