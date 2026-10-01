"""Platform admin: subscription plans (create/edit/toggle/delete, each with
a checklist of which FEATURE_PERMISSIONS modules it includes and a branch
cap), plus assigning a plan to an office. Also a public, read-only JSON
endpoint of active plans for the separate marketing/pricing website to
render pricing from.

An office's plan is enforced in two places, not here:
  - permissions.has_permission() (-> every feature_required() view and the
    sidebar's office_visible_features) checks the office's plan.
  - admin_branches' create action checks plan.max_branches.
This module only manages the plans themselves and who's on which one.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .forms import SubscriptionPlanForm
from .models import Office, SubscriptionPlan, SubscriptionPlanFeature
from .permissions import FEATURE_PERMISSIONS, get_request_office, is_office_admin, is_platform_admin

platform_required = user_passes_test(is_platform_admin)


def _feature_groups(checked_keys=()):
    """FEATURE_PERMISSIONS grouped by category, each with whether it's
    checked - for rendering the plan form's feature checklist."""
    checked = set(checked_keys)
    groups = {}
    for key, label, category in FEATURE_PERMISSIONS:
        groups.setdefault(category, []).append({'key': key, 'label': label, 'checked': key in checked})
    return [{'category': category, 'items': items} for category, items in groups.items()]


def _save_features(plan, request):
    """POST sends one 'feature_<key>' checkbox per FEATURE_PERMISSIONS entry
    (checked = included in this plan). Rebuild the plan's feature rows from
    whichever ones came through checked."""
    checked_keys = {key for key, _label, _category in FEATURE_PERMISSIONS if request.POST.get(f'feature_{key}') == 'on'}
    SubscriptionPlanFeature.objects.filter(plan=plan).exclude(feature_key__in=checked_keys).delete()
    existing = set(SubscriptionPlanFeature.objects.filter(plan=plan).values_list('feature_key', flat=True))
    SubscriptionPlanFeature.objects.bulk_create([
        SubscriptionPlanFeature(plan=plan, feature_key=key, is_enabled=True)
        for key in checked_keys - existing
    ])


@login_required
@platform_required
def platform_plans(request):
    """List every plan + the create panel."""
    if request.method == 'POST':
        form = SubscriptionPlanForm(request.POST, created_by=request.user)
        if form.is_valid():
            plan = form.save()
            _save_features(plan, request)
            messages.success(request, f'Plan "{plan.name}" created.')
            return redirect('employees:platform_plans')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = SubscriptionPlanForm()

    plans = list(SubscriptionPlan.objects.prefetch_related('features').order_by('order', 'price', 'name'))
    edit_data = {}
    for plan in plans:
        edit_data[str(plan.pk)] = {
            'url': f'/platform/plans/{plan.pk}/update/',
            'title': plan.name,
            'values': {
                'name': plan.name, 'slug': plan.slug, 'description': plan.description,
                'price': str(plan.price), 'is_free': plan.is_free,
                'duration_value': plan.duration_value, 'duration_unit': plan.duration_unit,
                'max_branches': plan.max_branches or '', 'max_employees': plan.max_employees or '',
                'is_active': plan.is_active, 'is_default': plan.is_default, 'is_featured': plan.is_featured,
                'order': plan.order,
            },
            'featureKeys': list(plan.enabled_feature_keys),
        }

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'plans': plans,
        'form': form,
        'feature_groups': _feature_groups(),
        'edit_data': edit_data,
        'form_has_errors': bool(form.is_bound and form.errors),
    })
    return render(request, 'employees/platform/plans.html', context)


@login_required
@platform_required
@require_http_methods(['POST'])
def platform_plan_update(request, pk):
    plan = get_object_or_404(SubscriptionPlan, pk=pk)
    form = SubscriptionPlanForm(request.POST, instance=plan)
    if form.is_valid():
        plan = form.save()
        _save_features(plan, request)
        messages.success(request, f'Plan "{plan.name}" updated.')
    else:
        errors = '; '.join(f"{form.fields[name].label or name}: {' '.join(errs)}" for name, errs in form.errors.items())
        messages.error(request, f'Could not update - {errors}')
    return redirect('employees:platform_plans')


@login_required
@platform_required
@require_http_methods(['POST'])
def platform_plan_toggle(request, pk):
    plan = get_object_or_404(SubscriptionPlan, pk=pk)
    plan.is_active = not plan.is_active
    plan.save(update_fields=['is_active', 'updated_at'])
    messages.success(request, f'Plan "{plan.name}" {"activated" if plan.is_active else "deactivated"}.')
    return redirect('employees:platform_plans')


@login_required
@platform_required
@require_http_methods(['POST'])
def platform_plan_delete(request, pk):
    plan = get_object_or_404(SubscriptionPlan, pk=pk)
    offices_on_it = plan.office_count
    name = plan.name
    plan.delete()  # Office.plan is SET_NULL - those offices just go back to "unrestricted", not broken
    extra = f' {offices_on_it} office(s) that were on it are now unrestricted (no plan).' if offices_on_it else ''
    messages.success(request, f'Plan "{name}" deleted.{extra}')
    return redirect('employees:platform_plans')


@login_required
@platform_required
@require_http_methods(['POST'])
def platform_office_set_plan(request, pk):
    """Assign/change which plan an office is on - from the office
    approvals/list screen, independent of approve/reject/suspend."""
    office = get_object_or_404(Office, pk=pk)
    plan_id = request.POST.get('plan_id')
    if not plan_id:
        office.plan = None
        office.plan_assigned_at = None
        office.save(update_fields=['plan', 'plan_assigned_at', 'updated_at'])
        messages.success(request, f'{office.name} is now unrestricted (no plan).')
    else:
        plan = get_object_or_404(SubscriptionPlan, pk=plan_id)
        office.set_plan(plan, request.user)
        messages.success(request, f'{office.name} is now on the "{plan.name}" plan.')
    return redirect(request.POST.get('next') or 'employees:platform_office_approvals')


@login_required
@user_passes_test(is_office_admin)
def choose_plan(request):
    """An office admin picks (or changes) their own office's plan - the
    page an office with no plan lands on, since office_feature_enabled()
    hides every gated module until one's chosen. Self-service: there's no
    payment step here, picking a plan applies it immediately. A platform
    admin can still override this from Office Approvals."""
    office = get_request_office(request)
    if office is None:
        messages.error(request, 'Your account is not linked to an approved office.')
        return redirect('employees:employee_dashboard')

    if request.method == 'POST':
        plan = get_object_or_404(SubscriptionPlan, pk=request.POST.get('plan_id'), is_active=True)
        office.set_plan(plan, request.user)
        messages.success(request, f'You\'re now on the "{plan.name}" plan.')
        return redirect('employees:choose_plan')

    plans = list(SubscriptionPlan.objects.filter(is_active=True).prefetch_related('features').order_by('order', 'price', 'name'))
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'plans': plans,
        'current_plan': office.plan,
    })
    return render(request, 'employees/platform/choose_plan.html', context)


def public_plans_api(request):
    """Public, read-only: active plans for the separate pricing page to
    render. No auth - this is meant to be fetched from outside the app."""
    plans = (
        SubscriptionPlan.objects.filter(is_active=True)
        .prefetch_related('features')
        .order_by('order', 'price', 'name')
    )
    feature_labels = {key: label for key, label, _category in FEATURE_PERMISSIONS}
    return JsonResponse({
        'plans': [
            {
                'slug': plan.slug,
                'name': plan.name,
                'description': plan.description,
                'price': str(plan.price),
                'is_free': plan.is_free,
                'duration_value': plan.duration_value,
                'duration_unit': plan.duration_unit,
                'duration_display': plan.duration_display,
                'is_featured': plan.is_featured,
                'max_branches': plan.max_branches,
                'max_employees': plan.max_employees,
                'features': [feature_labels.get(key, key) for key in sorted(plan.enabled_feature_keys)],
            }
            for plan in plans
        ],
    })
