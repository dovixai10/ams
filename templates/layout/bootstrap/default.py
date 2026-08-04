"""
This is a default Bootstrap class for the theme level.
Used as fallback when specific layout bootstrap is not found.
"""


class TemplateBootstrapDefault:
    def init(context):
        context.update(
            {
                "layout": "vertical",
                "content_layout": "compact",
                "is_navbar": True,
                "is_menu": True,
                "is_footer": True,
                "container_class": "container-xxl",
                "content_layout_class": "layout-compact",
                "navbar_type_class": "",
                "header_type_class": "",
                "menu_collapsed_class": "",
                "footer_fixed_class": "",
                "display_customizer_class": "",
                "skins": "default",
                "theme": "light",
                "text_direction_value": "ltr",
                "menu_horizontal": False,
                "is_front": False,
                "is_flex": False,
                "url": "/",
            }
        )
        return context
