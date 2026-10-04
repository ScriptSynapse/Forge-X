"""Storage locations administration (/admin/locations, administrators only)."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..auth.decorators import ADMIN, roles_required
from . import services
from .forms import LocationForm

bp = Blueprint("locations", __name__, url_prefix="/admin/locations")


@bp.route("", methods=["GET", "POST"])
@roles_required(ADMIN)
def index():
    form = LocationForm()
    if form.validate_on_submit():
        try:
            services.create_location(form.location_name.data, form.location_type.data, form.description.data)
        except services.LocationError as err:
            form.location_name.errors.append(str(err))
        else:
            flash(f"Location {form.location_name.data} added.", "success")
            return redirect(url_for("locations.index"))
    return render_template("locations/index.html", form=form, locations=services.list_locations())


@bp.route("/<int:location_id>/edit", methods=["GET", "POST"])
@roles_required(ADMIN)
def edit(location_id):
    location = services.get_location(location_id)
    if location is None:
        abort(404)
    form = LocationForm()
    if request.method == "GET":
        form.location_name.data = location["location_name"]
        form.location_type.data = location["location_type"]
        form.description.data = location["description"]
    if form.validate_on_submit():
        try:
            changed = services.update_location(location_id, form.location_name.data, form.location_type.data,
                                               form.description.data)
        except services.LocationError as err:
            form.location_name.errors.append(str(err))
        else:
            flash("Location updated." if changed else "No changes to save.", "success" if changed else "info")
            return redirect(url_for("locations.index"))
    return render_template("locations/edit.html", form=form, location=location)


@bp.post("/<int:location_id>/status")
@roles_required(ADMIN)
def set_status(location_id):
    active = request.form.get("action") == "activate"
    try:
        services.set_active(location_id, active)
    except services.LocationError as err:
        flash(str(err), "danger")
    else:
        flash("Location activated." if active else "Location deactivated. Items already there are unaffected; "
              "new transfers to it will be refused.", "success")
    return redirect(url_for("locations.index"))
