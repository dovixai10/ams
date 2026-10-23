"""Recruitment - public careers page. No login required - mirrors
crm_views.crm_public_lead_page's shape exactly: one view handles both the
GET (list OPEN jobs, optionally filtered/sorted, or show one job's detail +
apply form) and the POST (the application submission) for a single URL per
office."""
from html.parser import HTMLParser

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .models import Department, EmploymentType, Job, JobApplication, RecruitmentCareersPage
from .views import get_client_ip

EXPERIENCE_BUCKETS = [
    ('0-2', '0 - 2 Years', 0, 2),
    ('2-5', '2 - 5 Years', 2, 5),
    ('5-10', '5 - 10 Years', 5, 10),
    ('10+', '10+ Years', 10, 999),
]

SORT_CHOICES = [
    ('recent', 'Most Recent'),
    ('oldest', 'Oldest First'),
    ('title', 'Title A-Z'),
]

MAX_RESUME_SIZE = 5 * 1024 * 1024  # 5 MB, matches the "Max 5 MB" label on the upload box


def _safe_decimal(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        from decimal import Decimal, InvalidOperation
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


class _BulletExtractor(HTMLParser):
    """Pulls the text of every <li> out of a job's rich-text description, so
    the apply page's 'What you'll do' card shows the admin's own bullet
    points instead of inventing responsibilities that were never written."""

    def __init__(self):
        super().__init__()
        self.bullets = []
        self._in_li = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == 'li':
            self._in_li = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == 'li' and self._in_li:
            text = ''.join(self._buf).strip()
            if text:
                self.bullets.append(text)
            self._in_li = False

    def handle_data(self, data):
        if self._in_li:
            self._buf.append(data)


def _extract_bullets(description_html, limit=6):
    if not description_html:
        return []
    parser = _BulletExtractor()
    try:
        parser.feed(description_html)
    except Exception:
        return []
    return parser.bullets[:limit]


def recruitment_public_careers_page(request, slug):
    page = get_object_or_404(RecruitmentCareersPage.objects.select_related('office'), slug=slug, is_active=True)
    office = page.office
    submitted = False

    open_jobs = Job.objects.filter(office=office, status=Job.Status.OPEN).select_related('department', 'employment_type', 'branch')

    selected_job_slug = request.POST.get('job') if request.method == 'POST' else request.GET.get('job')
    selected_job = open_jobs.filter(slug=selected_job_slug).first() if selected_job_slug else None

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        current_location = request.POST.get('current_location', '').strip()
        message = request.POST.get('message', '').strip()
        years_of_experience = request.POST.get('years_of_experience', '').strip()
        consent_given = request.POST.get('consent') == 'on'
        resume = request.FILES.get('resume')

        if not (full_name and email and phone and current_location and years_of_experience and message and resume):
            messages.error(request, 'Please fill in every required field and attach your resume.')
        elif years_of_experience not in JobApplication.YearsOfExperience.values:
            messages.error(request, 'Please select your years of experience.')
        elif not consent_given:
            messages.error(request, 'Please agree to the privacy policy to submit your application.')
        elif resume.size > MAX_RESUME_SIZE:
            messages.error(request, 'Resume must be 5 MB or smaller.')
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
                current_location=current_location,
                years_of_experience=years_of_experience,
                linkedin_url=request.POST.get('linkedin_url', '').strip(),
                portfolio_url=request.POST.get('portfolio_url', '').strip(),
                current_ctc=_safe_decimal(request.POST.get('current_ctc')),
                expected_ctc=_safe_decimal(request.POST.get('expected_ctc')),
                department=selected_job.department if selected_job else None,
                designation=selected_job.designation if selected_job else None,
                employment_type=selected_job.employment_type if selected_job else None,
                resume=resume,
                message=message,
                source=JobApplication.Source.WEBSITE,
                consent_given_at=timezone.now(),
                consent_ip_address=get_client_ip(request),
            )
            application.log_activity('Applied via the careers page')
            submitted = True

    # --- Filters + sort, for the job grid (only relevant when not viewing a single job) ---
    jobs_qs = open_jobs
    q = request.GET.get('q', '').strip()
    if q:
        jobs_qs = jobs_qs.filter(Q(title__icontains=q) | Q(required_skills__icontains=q))
    department_id = request.GET.get('department', '').strip()
    if department_id.isdigit():
        jobs_qs = jobs_qs.filter(department_id=int(department_id))
    location = request.GET.get('location', '').strip()
    if location:
        jobs_qs = jobs_qs.filter(Q(location__iexact=location) | Q(branch__name__iexact=location))
    employment_type_ids = {int(i) for i in request.GET.getlist('employment_type') if i.isdigit()}
    if employment_type_ids:
        jobs_qs = jobs_qs.filter(employment_type_id__in=employment_type_ids)

    jobs = list(jobs_qs.order_by('-created_at'))

    experience_bucket = request.GET.get('experience', '').strip()
    bucket_match = next((b for b in EXPERIENCE_BUCKETS if b[0] == experience_bucket), None)
    if bucket_match:
        _, _, b_min, b_max = bucket_match
        def _overlaps(job):
            jmin = job.experience_min if job.experience_min is not None else 0
            jmax = job.experience_max if job.experience_max is not None else 999
            return jmax >= b_min and jmin <= b_max
        jobs = [j for j in jobs if _overlaps(j)]

    sort = request.GET.get('sort', 'recent').strip()
    if sort == 'oldest':
        jobs.sort(key=lambda j: j.created_at)
    elif sort == 'title':
        jobs.sort(key=lambda j: j.title.lower())

    filters_qs = request.GET.copy()
    filters_qs.pop('job', None)
    filters_qs = filters_qs.urlencode()

    department_choices = Department.objects.filter(office=office, is_active=True).order_by('name')
    employment_type_choices = EmploymentType.objects.filter(office=office, is_active=True).order_by('name')
    location_choices = sorted({
        j.location.strip() if j.location else (j.branch.name if j.branch else '')
        for j in open_jobs if (j.location and j.location.strip()) or j.branch
    })

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
        'hide_mobile_nav': True,
        'show_mobile_nav': False,
        'office': office,
        'page': page,
        'jobs': jobs,
        'total_open_jobs': open_jobs.count(),
        'selected_job': selected_job,
        'selected_job_bullets': _extract_bullets(selected_job.description) if selected_job else [],
        'years_of_experience_choices': JobApplication.YearsOfExperience.choices,
        'submitted': submitted,
        'q': q,
        'department_choices': department_choices,
        'employment_type_choices': employment_type_choices,
        'location_choices': location_choices,
        'department_filter': department_id,
        'location_filter': location,
        'employment_type_filter_ids': employment_type_ids,
        'experience_filter': experience_bucket,
        'experience_buckets': EXPERIENCE_BUCKETS,
        'sort': sort,
        'sort_choices': SORT_CHOICES,
        'filters_qs': filters_qs,
    })
    return render(request, 'employees/recruitment/public_careers_page.html', context)
