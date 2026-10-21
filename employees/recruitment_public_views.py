"""Recruitment - public careers page. No login required - mirrors
crm_views.crm_public_lead_page's shape exactly: one view handles both the
GET (list OPEN jobs + optionally show one job's detail/apply form) and the
POST (the application submission) for a single URL per office."""
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .models import Job, JobApplication, RecruitmentCareersPage


def _safe_decimal(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        from decimal import Decimal, InvalidOperation
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def recruitment_public_careers_page(request, slug):
    page = get_object_or_404(RecruitmentCareersPage.objects.select_related('office'), slug=slug, is_active=True)
    office = page.office
    submitted = False

    jobs = Job.objects.filter(office=office, status=Job.Status.OPEN).order_by('-created_at')

    selected_job_slug = request.POST.get('job') if request.method == 'POST' else request.GET.get('job')
    selected_job = jobs.filter(slug=selected_job_slug).first() if selected_job_slug else None

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        resume = request.FILES.get('resume')

        if not (full_name and email and phone and resume):
            messages.error(request, 'Please fill in your name, email, phone, and attach your resume.')
        elif selected_job and JobApplication.objects.filter(job=selected_job).filter(
            Q(email__iexact=email) | Q(phone=phone)
        ).exists():
            messages.error(request, "You've already applied for this job - we have your application on file.")
        else:
            application = JobApplication.objects.create(
                job=selected_job,
                office=office,
                branch=selected_job.branch if selected_job else None,
                full_name=full_name,
                email=email,
                phone=phone,
                current_location=request.POST.get('current_location', '').strip(),
                current_company=request.POST.get('current_company', '').strip(),
                current_ctc=_safe_decimal(request.POST.get('current_ctc')),
                expected_ctc=_safe_decimal(request.POST.get('expected_ctc')),
                department=selected_job.department if selected_job else None,
                designation=selected_job.designation if selected_job else None,
                employment_type=selected_job.employment_type if selected_job else None,
                resume=resume,
                message=request.POST.get('message', '').strip(),
                source=JobApplication.Source.WEBSITE,
            )
            application.log_activity('Applied via the careers page')
            submitted = True

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
        'hide_mobile_nav': True,
        'show_mobile_nav': False,
        'office': office,
        'page': page,
        'jobs': jobs,
        'selected_job': selected_job,
        'submitted': submitted,
    })
    return render(request, 'employees/recruitment/public_careers_page.html', context)
