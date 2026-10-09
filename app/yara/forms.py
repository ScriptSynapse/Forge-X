"""YARA forms."""
from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from ..auth.forms import strip

SOURCE_HELP = "YARA rule source. It is compiled in an isolated worker before saving; include directives are not allowed."


class RuleForm(FlaskForm):
    name = StringField("Library name", filters=[strip],
                       validators=[DataRequired("Name the rule."), Length(min=2, max=100),
                                   Regexp(r"^[A-Za-z0-9 ._-]+$", message="Use letters, numbers, spaces, dots, dashes or underscores.")])
    description = StringField("Description", filters=[strip], validators=[Optional(), Length(max=500)])
    author = StringField("Author", filters=[strip], validators=[Optional(), Length(max=100)])
    scope = SelectField("Applies to", choices=[("All cases", "All cases"), ("Selected cases", "Selected cases only")])
    source = TextAreaField("Rule source", validators=[DataRequired("Paste the rule source.")])


class VersionForm(FlaskForm):
    source = TextAreaField("Rule source", validators=[DataRequired("Paste the rule source.")])
    change_note = StringField("What changed", filters=[strip], validators=[DataRequired("Say what changed."), Length(min=3, max=255)])


class ScopeForm(FlaskForm):
    scope = SelectField("Applies to", choices=[("All cases", "All cases"), ("Selected cases", "Selected cases only")])


class CaseLinkForm(FlaskForm):
    case_id = SelectField("Case", coerce=int)
