from rest_framework import status
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import is_employee
from .serializers import EmployeeProfileSerializer, SalarySlipSerializer


class TokenAuthView(ObtainAuthToken):
    """Same as DRF's default obtain_auth_token, but never goes through
    SessionAuthentication. A stray session cookie in the client (e.g.
    Postman auto-attaching one from an earlier browser login) would
    otherwise make DRF enforce CSRF on this endpoint - which makes no
    sense for a public username/password -> token exchange."""

    authentication_classes = []


class EmployeeProfileAPIView(APIView):
    """Read-only endpoint returning the logged-in employee's own profile
    (personal info, employment details, leave balance, current salary) as
    JSON. Authenticate with a DRF token (see /api/v1/token-auth/) so other
    platforms can call this directly."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_employee(request.user):
            return Response(
                {'detail': 'Only employee accounts can access this endpoint.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        employee = request.user.employee_profile
        serializer = EmployeeProfileSerializer(employee, context={'request': request})
        return Response(serializer.data)


class SalarySlipListAPIView(APIView):
    """Read-only endpoint returning the logged-in employee's own salary
    slips (one entry per generated month), each with an absolute `pdf_url`
    to fetch/download that month's payslip PDF. Same auth as /api/v1/profile/
    - a DRF token via /api/v1/token-auth/."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_employee(request.user):
            return Response(
                {'detail': 'Only employee accounts can access this endpoint.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        from .models import SalarySlip

        employee = request.user.employee_profile
        slips = SalarySlip.objects.filter(employee=employee).order_by('-month')
        serializer = SalarySlipSerializer(slips, many=True, context={'request': request})
        print("serializer.data->",serializer.data)
        return Response(serializer.data)
