"""Administrator forms for accounts and roles."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, EqualTo, Length, Regexp

from ..auth.forms import EMAIL_RE, USERNAME_RE, PasswordRules, strip


class CreateUserForm(FlaskForm):
    full_name = StringField("Full name", filters=[strip], validators=[DataRequired("Enter a full name."), Length(min=2, max=100)])
    email = StringField("Email", filters=[strip, lambda v: v.lower() if isinstance(v, str) else v],
                        validators=[DataRequired("Enter an email."), Length(max=254),
                                    Regexp(EMAIL_RE, message="Enter a valid email address.")])
    username = StringField("Username", filters=[strip],
                           validators=[DataRequired("Choose a username."),
                                       Regexp(USERNAME_RE, message="Use 3 to 30 letters, numbers, dots or underscores.")])
    role_id = SelectField("Role", coerce=int, validators=[DataRequired("Choose a role.")])
    password = PasswordField("Temporary password",
                             validators=[DataRequired("Set a temporary password."), PasswordRules("username")])
    confirm = PasswordField("Confirm temporary password",
                            validators=[DataRequired("Confirm the password."),
                                        EqualTo("password", message="Passwords don't match.")])
    must_change = BooleanField("Require a new password at first login", default=True)


class RoleForm(FlaskForm):
    role_id = SelectField("Add role", coerce=int, validators=[DataRequired("Choose a role.")])


class ResetPasswordForm(FlaskForm):
    password = PasswordField("Temporary password", validators=[DataRequired("Set a temporary password."), PasswordRules()])
    confirm = PasswordField("Confirm temporary password",
                            validators=[DataRequired("Confirm the password."),
                                        EqualTo("password", message="Passwords don't match.")])


class EditUserForm(FlaskForm):
    """An administrator corrects a person's name, email or username.
    Roles, status and passwords have their own, separately audited actions."""
    full_name = StringField("Full name", filters=[strip],
                            validators=[DataRequired("Enter the full name."), Length(min=2, max=100)])
    email = StringField("Email", filters=[strip],
                        validators=[DataRequired("Enter an email address."), Length(max=254),
                                    Regexp(EMAIL_RE, message="Enter a valid email address.")])
    username = StringField("Username", filters=[strip],
                           validators=[DataRequired("Enter a username."),
                                       Regexp(USERNAME_RE, message="Use 3 to 30 letters, numbers, dots or underscores.")])
