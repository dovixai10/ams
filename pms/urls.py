from django.urls import path

from . import views

app_name = 'pms'

urlpatterns = [
    path('', views.pms_hub, name='hub'),
    path('people-access/', views.people_access_hub, name='people_access_hub'),

    # Roles
    path('roles/', views.role_list, name='role_list'),
    path('roles/create/', views.role_create, name='role_create'),
    path('roles/<int:pk>/', views.role_detail, name='role_detail'),
    path('roles/<int:pk>/edit/', views.role_edit, name='role_edit'),
    path('roles/<int:pk>/delete/', views.role_delete, name='role_delete'),
    path('roles/<int:pk>/clone/', views.role_clone, name='role_clone'),

    # Permissions
    path('permissions/', views.permission_catalog, name='permission_catalog'),
    path('permissions/<int:permission_id>/roles/', views.permission_roles_api, name='permission_roles_api'),
    path('module-permissions/', views.module_permissions, name='module_permissions'),

    # Users
    path('users/', views.user_list, name='user_list'),
    path('users/revoke-role/', views.user_revoke_role, name='user_revoke_role'),
    path('users/<int:user_id>/toggle-active/', views.user_toggle_active, name='user_toggle_active'),

    # Skills
    path('skills/', views.skill_list, name='skill_list'),
    path('skills/assign/', views.skill_assign, name='skill_assign'),

    # Groups
    path('groups/', views.group_list, name='group_list'),
    path('groups/create/', views.group_create, name='group_create'),
    path('groups/<int:pk>/edit/', views.group_edit, name='group_edit'),
    path('groups/<int:pk>/delete/', views.group_delete, name='group_delete'),

    # Availability & status
    path('availability/', views.user_availability, name='user_availability'),
    path('status/', views.user_status, name='user_status'),
]
