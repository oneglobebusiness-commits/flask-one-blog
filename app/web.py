"""HTML pages and uploaded images."""
import os

from flask import Blueprint, current_app, render_template, send_from_directory

web = Blueprint("web", __name__)

LIST_PAGES = {
    "contents": dict(kind="contents", title="Blog Management", subtitle="Manage all your blogs: edit, publish, schedule, or save as draft", empty="No blogs found", empty_hint="Try adjusting your search or filters"),
    "draft": dict(kind="draft", title="Draft Blogs", subtitle="Manage your draft blogs: edit, publish, schedule, or continue writing", empty="No drafts found", empty_hint="All your draft blogs will appear here."),
    "schedule": dict(kind="schedule", title="Scheduled Blogs", subtitle="Manage your scheduled blog posts: edit, reschedule, or publish now", empty="No scheduled blogs found", empty_hint="Schedule your drafts to see them here"),
    "publish": dict(kind="publish", title="Published Blogs", subtitle="View all your published blog posts", empty="No published blogs found", empty_hint="Publish your drafts to see them here"),
}


@web.get("/")
def landing():
    return render_template("landing.html")


@web.get("/welcome")
def welcome():
    return render_template("welcome.html")


@web.get("/dashboard")
def dashboard():
    return render_template("dashboard.html", active="dashboard")


@web.get("/billings")
def billings():
    return render_template("billings.html", active="billings")


@web.get("/contents")
def contents():
    return render_template("blogs.html", active="contents", page=LIST_PAGES["contents"])


@web.get("/draft")
def draft():
    return render_template("blogs.html", active="draft", page=LIST_PAGES["draft"])


@web.get("/Schedule")
@web.get("/schedule")
def schedule():
    return render_template("blogs.html", active="schedule", page=LIST_PAGES["schedule"])


@web.get("/publish")
def publish():
    return render_template("blogs.html", active="publish", page=LIST_PAGES["publish"])


@web.get("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(os.path.join(current_app.config["UPLOAD_DIR"]), filename)
