"""Login, signup and password forms (Flask-WTF adds a CSRF token to each)."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, Optional, Regexp, ValidationError

from .passwords import MAX_LENGTH, password_problems

USERNAME_RE = r"^[A-Za-z0-9._]{3,30}$"
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def strip(value):
    return value.strip() if isinstance(value, str) else value


class LoginForm(FlaskForm):
    login = StringField("Username or email", filters=[strip],
                        validators=[DataRequired("Enter your username or email."), Length(max=254)])
    password = PasswordField("Password", validators=[DataRequired("Enter your password."), Length(max=MAX_LENGTH)])
    remember = BooleanField("Keep me logged in on this device for 7 days")


class PasswordRules:
    """Validator applying the password policy (uses the form's username if present)."""

    def __init__(self, username_field=None):
        self.username_field = username_field

    def __call__(self, form, field):
        username = None
        if self.username_field and self.username_field in form:
            username = form[self.username_field].data
        problems = password_problems(field.data, username)
        if problems:
            raise ValidationError(" ".join(problems))


class SignupForm(FlaskForm):
    full_name = StringField("Full name", filters=[strip],
                            validators=[DataRequired("Enter your full name."), Length(min=2, max=100)])
    email = StringField("Email", filters=[strip, lambda v: v.lower() if isinstance(v, str) else v],
                        validators=[DataRequired("Enter your email."), Length(max=254),
                                    Regexp(EMAIL_RE, message="Enter a valid email address.")])
    username = StringField("Username", filters=[strip],
                           validators=[DataRequired("Choose a username."),
                                       Regexp(USERNAME_RE, message="Use 3 to 30 letters, numbers, dots or underscores.")])
    password = PasswordField("Password", validators=[DataRequired("Choose a password."), PasswordRules("username")])
    confirm = PasswordField("Confirm password",
                            validators=[DataRequired("Confirm your password."),
                                        EqualTo("password", message="Passwords don't match.")])
    reason = TextAreaField("Reason for access", filters=[strip], validators=[Optional(), Length(max=500)])


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired("Enter your current password.")])
    new_password = PasswordField("New password", validators=[DataRequired("Choose a new password."),
                                                             Length(max=MAX_LENGTH)])
    confirm = PasswordField("Confirm new password",
                            validators=[DataRequired("Confirm your new password."),
                                        EqualTo("new_password", message="Passwords don't match.")])
