"""Case forms (Flask-WTF adds a CSRF token to each)."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length

from ..auth.forms import strip
from .services import EDITABLE_STATUSES, PRIORITIES


class CaseForm(FlaskForm):
    """Create and edit share these fields. `lead_user_id` is only used on create."""
    title = StringField("Title", filters=[strip],
                        validators=[DataRequired("Enter a short, factual title."), Length(min=4, max=200)])
    case_type_id = SelectField("Case type", coerce=int, validators=[DataRequired("Choose a case type.")])
    priority = SelectField("Priority", choices=[(p, p) for p in PRIORITIES], default="Medium",
                           validators=[DataRequired("Choose a priority.")])
    description = TextAreaField("Description", filters=[strip],
                                validators=[DataRequired("Describe what happened and what the lab has been asked to do."),
                                            Length(min=10, max=5000)])
    lead_user_id = SelectField("Lead investigator", coerce=int)
    version = HiddenField()


class StatusForm(FlaskForm):
    status = SelectField("Status", choices=[(s, s) for s in EDITABLE_STATUSES])


class AssignForm(FlaskForm):
    user_id = SelectField("Investigator", coerce=int, validators=[DataRequired("Choose an investigator.")])
    make_lead = BooleanField("Make this investigator the lead")


class CloseForm(FlaskForm):
    summary = TextAreaField("Closure summary", filters=[strip],
                            validators=[DataRequired("Summarise the outcome before closing."), Length(min=10, max=1000)])
    confirm = BooleanField("I understand a closed case can't be reopened or edited.",
                           validators=[DataRequired("Tick the box to confirm.")])


class DeleteCaseForm(FlaskForm):
    reason = TextAreaField("Why is this case being deleted?", filters=[strip],
                           validators=[DataRequired("Give a reason."), Length(min=10, max=300)])
    confirm_reference = StringField("Type the case reference to confirm", filters=[strip],
                                    validators=[DataRequired("Type the case reference.")])
