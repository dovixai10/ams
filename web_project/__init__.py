
# from web_project.bootstrap import TemplateBootstrap
from web_project.template_helpers.theme import TemplateHelper
from django.conf import settings


class TemplateLayout:
    # Initialize the bootstrap files and page layout
    @staticmethod
    def init(request_or_view, context):
        # Init the Template Context using TEMPLATE_CONFIG

        request = None
        if hasattr(request_or_view, "request"):
            request = getattr(request_or_view, "request", None)
        elif hasattr(request_or_view, "META") and hasattr(request_or_view, "user"):
            request = request_or_view
        elif isinstance(request_or_view, dict):
            request = request_or_view.get("request")

        if request is not None:
            user = getattr(request, "user", None)
            if getattr(user, "is_authenticated", False):
                if getattr(user, "is_superuser", False):
                    context.setdefault("is_navbar", False)
                    context.setdefault("navbar_hide_toggle", True)
                    context.setdefault("hide_mobile_nav", True)
                elif hasattr(user, "employee_profile"):
                    context.setdefault("is_navbar", False)
                    context.setdefault("is_menu", False)

        # Set a default layout globally using settings.py. Can be set in the page level view file as well.
        layout = "vertical"

        # Set the selected layout
        context.update(
            {
                "layout_path": TemplateHelper.set_layout(
                    "layout_" + layout + ".html", context
                ),
            }
        )

        # Map context variables
        TemplateHelper.map_context(context)

        return context
