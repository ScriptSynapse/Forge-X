from flask_wtf import FlaskForm
from wtforms import SelectField, StringField
from wtforms.validators import DataRequired, Length, Optional

from ..auth.forms import strip
from .services import LOCATION_TYPES


class LocationForm(FlaskForm):
    location_name = StringField("Name", filters=[strip],
                                validators=[DataRequired("Enter a name, e.g. Vault C, Shelf 1."), Length(min=2, max=100)])
    location_type = SelectField("Type", choices=[(t, t) for t in LOCATION_TYPES])
    description = StringField("Description", filters=[strip], validators=[Optional(), Length(max=255)])
