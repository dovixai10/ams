"""
Notification utility functions for creating notifications throughout the system.
Use these functions to create notifications when events occur.
"""

from django.utils import timezone
from .models import EmployeeNotification, Employee


def create_notification(employee, notification_type, title, message, action_url=''):
    """
    Create a notification for an employee, and push it to their phone.

    Args:
        employee (Employee): Employee object or employee ID
        notification_type (str): Type from EmployeeNotification.NotificationType
        title (str): Notification title
        message (str): Notification message
        action_url (str): Optional URL to action page

    Returns:
        EmployeeNotification: Created notification object

    Example:
        create_notification(
            employee=employee,
            notification_type='task_assigned',
            title='New Task Assigned',
            message='You have been assigned: Complete Project Report',
            action_url='/tasks/123/'
        )

    This is the single choke point every notification in the app already
    goes through (task assigned, leave approved/rejected, face update
    decided, ticket resolved, ...), so it's also the one place a push
    notification gets sent from - every existing and future caller gets
    push for free, no per-call-site changes needed. Push is best-effort
    (see push_utils.send_push_to_employee): if Firebase isn't configured
    yet, or the send fails, the in-app notification above still succeeds
    either way - this function's return value/behavior doesn't change.
    """
    if isinstance(employee, int):
        employee = Employee.objects.get(id=employee)

    notification = EmployeeNotification.objects.create(
        employee=employee,
        office=employee.office,
        branch=employee.branch,
        notification_type=notification_type,
        title=title,
        message=message,
        action_url=action_url,
        is_read=False,
    )

    from .push_utils import send_push_to_employee
    from .mobile_notifications_api import _spec_type
    send_push_to_employee(
        employee, title, message,
        # Same field names/shape as GET /notifications so the app can reuse
        # one notification model for both the list screen and a push tap.
        data={
            'notificationId': f'ntf_{notification.id}',
            'type': _spec_type(notification_type),
            'deepLink': action_url,
        },
    )

    return notification


def create_task_notification(employee, task):
    """Create notification when task is assigned"""
    return create_notification(
        employee=employee,
        notification_type='task_assigned',
        title='Task Assigned',
        message=f'You have been assigned: {task.title}',
        action_url=f'/tasks/{task.id}/'
    )


def create_leave_approved_notification(employee, leave_request):
    """Create notification when leave is approved"""
    return create_notification(
        employee=employee,
        notification_type='leave_approved',
        title='Leave Request Approved ✅',
        message=f'Your leave request for {leave_request.start_date} to {leave_request.end_date} has been approved.',
        action_url=f'/leave/requests/'
    )


def create_leave_rejected_notification(employee, leave_request):
    """Create notification when leave is rejected"""
    return create_notification(
        employee=employee,
        notification_type='leave_rejected',
        title='Leave Request Rejected ❌',
        message=f'Your leave request for {leave_request.start_date} to {leave_request.end_date} has been rejected.',
        action_url=f'/leave/requests/'
    )


def create_face_approved_notification(employee):
    """Create notification when face update is approved"""
    return create_notification(
        employee=employee,
        notification_type='face_approved',
        title='Face Update Approved ✅',
        message='Your face recognition update has been approved.',
        action_url=f'/face/register/'
    )


def create_face_rejected_notification(employee):
    """Create notification when face update is rejected"""
    return create_notification(
        employee=employee,
        notification_type='face_rejected',
        title='Face Update Rejected ❌',
        message='Your face recognition update has been rejected. Please try again.',
        action_url=f'/face/register/'
    )


def create_loan_approved_notification(employee, loan_request):
    """Create notification when loan is approved"""
    return create_notification(
        employee=employee,
        notification_type='loan_approved',
        title='Loan Request Approved ✅',
        message=f'Your loan request for ₹{loan_request.amount} has been approved.',
        action_url=f'/loans/my-loans/'
    )


def create_loan_rejected_notification(employee, loan_request):
    """Create notification when loan is rejected"""
    return create_notification(
        employee=employee,
        notification_type='loan_rejected',
        title='Loan Request Rejected ❌',
        message=f'Your loan request for ₹{loan_request.amount} has been rejected.',
        action_url=f'/loans/my-loans/'
    )


def create_reimbursement_approved_notification(employee, reimbursement):
    """Create notification when reimbursement is approved"""
    return create_notification(
        employee=employee,
        notification_type='reimbursement_approved',
        title='Reimbursement Approved ✅',
        message=f'Your reimbursement request for ₹{reimbursement.amount} has been approved.',
        action_url=f'/reimbursements/my-reimbursements/'
    )


def create_reimbursement_rejected_notification(employee, reimbursement):
    """Create notification when reimbursement is rejected"""
    return create_notification(
        employee=employee,
        notification_type='reimbursement_rejected',
        title='Reimbursement Rejected ❌',
        message=f'Your reimbursement request for ₹{reimbursement.amount} has been rejected.',
        action_url=f'/reimbursements/my-reimbursements/'
    )


def create_id_card_generated_notification(employee):
    """Create notification when ID card is generated"""
    return create_notification(
        employee=employee,
        notification_type='id_card_generated',
        title='ID Card Generated 📄',
        message='Your employee ID card has been generated and is ready for download.',
        action_url=f'/id-card/'
    )


def create_asset_assigned_notification(employee, asset):
    """Create notification when asset is assigned"""
    return create_notification(
        employee=employee,
        notification_type='asset_assigned',
        title='Asset Assigned 📦',
        message=f'You have been assigned: {asset.asset_name}',
        action_url=f'/services/assets/'
    )


def create_asset_return_requested_notification(employee, asset):
    """Create notification when asset return is requested"""
    return create_notification(
        employee=employee,
        notification_type='asset_return_requested',
        title='Asset Return Requested 🔄',
        message=f'Please return the assigned asset: {asset.asset_name}',
        action_url=f'/services/assets/'
    )


def create_ticket_created_notification(employee, ticket):
    """Create notification when support ticket is created"""
    return create_notification(
        employee=employee,
        notification_type='ticket_created',
        title='Support Ticket Created 🎫',
        message=f'Your support ticket has been created: {ticket.subject}',
        action_url=f'/tickets/{ticket.id}/'
    )


def create_ticket_resolved_notification(employee, ticket):
    """Create notification when support ticket is resolved"""
    return create_notification(
        employee=employee,
        notification_type='ticket_resolved',
        title='Support Ticket Resolved ✅',
        message=f'Your support ticket has been resolved: {ticket.subject}',
        action_url=f'/tickets/{ticket.id}/'
    )


def create_document_required_notification(employee, document_type):
    """Create notification when document is required"""
    return create_notification(
        employee=employee,
        notification_type='document_required',
        title='Document Required 📋',
        message=f'Please upload required document: {document_type}',
        action_url=f'/profile/documents/'
    )


def create_document_verified_notification(employee, document_type):
    """Create notification when document is verified"""
    return create_notification(
        employee=employee,
        notification_type='document_verified',
        title='Document Verified ✅',
        message=f'Your {document_type} has been verified.',
        action_url=f'/profile/documents/'
    )


def create_rule_update_notification(employee, rule_title):
    """Create notification when rules are updated"""
    return create_notification(
        employee=employee,
        notification_type='rule_update',
        title='Policy Update 📢',
        message=f'New policy update: {rule_title}',
        action_url=f'/rules/'
    )


def create_alert_notification(employee, message, action_url=''):
    """Create a generic alert notification"""
    return create_notification(
        employee=employee,
        notification_type='alert',
        title='Alert',
        message=message,
        action_url=action_url
    )


def mark_all_as_read(employee):
    """Mark all notifications as read for an employee"""
    count = EmployeeNotification.objects.filter(
        employee=employee,
        is_read=False
    ).update(
        is_read=True,
        read_at=timezone.now()
    )
    return count


def delete_old_notifications(employee, days=30):
    """Delete notifications older than specified days"""
    from datetime import timedelta
    cutoff_date = timezone.now() - timedelta(days=days)
    count, _ = EmployeeNotification.objects.filter(
        employee=employee,
        created_at__lt=cutoff_date,
        is_read=True
    ).delete()
    return count
