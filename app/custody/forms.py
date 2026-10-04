"""Custody transfer and correction forms."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, DateTimeLocalField, HiddenField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from ..auth.forms import strip


class TransferForm(FlaskForm):
    action = SelectField("Action", validators=[DataRequired("Choose what is happening to the item.")])
    to_user_id = SelectField("New custodian", coerce=int, validators=[DataRequired("Choose who receives the item.")])
    location_id = SelectField("Storage location", coerce=int, validators=[Optional()])
    location_note = StringField("Or describe the location", filters=[strip], validators=[Optional(), Length(max=200)])
    condition = StringField("Condition on handover", filters=[strip],
                            validators=[DataRequired("Describe the item's condition, e.g. Sealed, intact."), Length(max=200)])
    seal_number = StringField("Seal number", filters=[strip], validators=[Optional(), Length(max=30)])
    reason = TextAreaField("Reason", filters=[strip], validators=[DataRequired("Say why the item is moving."), Length(min=3, max=500)])
    occurred_at = DateTimeLocalField("When it happened", format="%Y-%m-%dT%H:%M", validators=[Optional()])
    expected_custodian_id = HiddenField()
    confirm = BooleanField("I confirm the item was physically handed over as described.",
                           validators=[DataRequired("Tick the box to confirm the handover.")])


class CorrectionForm(FlaskForm):
    to_user_id = SelectField("Correct custodian", coerce=int, validators=[DataRequired("Choose the custodian.")])
    location_id = SelectField("Correct storage location", coerce=int, validators=[Optional()])
    location_note = StringField("Or describe the location", filters=[strip], validators=[Optional(), Length(max=200)])
    condition = StringField("Condition", filters=[strip], validators=[DataRequired("Describe the condition."), Length(max=200)])
    seal_number = StringField("Seal number", filters=[strip], validators=[Optional(), Length(max=30)])
    reason = TextAreaField("What was wrong with the original entry?", filters=[strip],
                           validators=[DataRequired("Explain the correction."), Length(min=10, max=500)])
