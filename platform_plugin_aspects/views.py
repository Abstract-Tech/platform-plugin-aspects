"""
Endpoints for the Aspects platform plugin.
"""

from collections import namedtuple

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import exceptions, permissions
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from .utils import _, generate_guest_token, get_model

try:
    from openedx.core.lib.api.permissions import IsCourseStaffInstructor
except ImportError:

    class IsCourseStaffInstructor(permissions.BasePermission):
        """
        Permission class to use during tests.

        Importing from edx-platform doesn't work when running tests,
        so we declare our own permission class here.
        """

        def has_object_permission(self, request, view, obj):
            """
            Return False for security; mock this out during tests.
            """
            return False


# Course fields:
# * course_id: CourseKey; required by IsCourseStaffInstructor
# * display_name: str; optionally fetched from CourseOverview
Course = namedtuple("Course", ["course_id", "display_name"])


class SupersetView(GenericAPIView):
    """
    Superset-related endpoints provided by the aspects platform plugin.
    """

    authentication_classes = (SessionAuthentication,)
    permission_classes = (
        permissions.IsAuthenticated,
        IsCourseStaffInstructor,
    )

    lookup_field = "course_id"

    @property
    def allowed_methods(self):
        """
        Only POST is allowed for this view.
        """
        return ["post", "options", "head"]

    def get_object(self):
        """
        Return a Course-like object for the requested course_id.
        """
        course_id = self.kwargs.get(self.lookup_field, "")
        try:
            course_key = CourseKey.from_string(course_id)
        except InvalidKeyError as exc:
            raise exceptions.NotFound(
                _("Invalid course id: '{course_id}'").format(course_id=course_id)
            ) from exc

        # Fetch the CourseOverview (if we're running in edx-platform)
        CourseOverview = get_model("course_overviews")
        if CourseOverview:
            course_overview = CourseOverview.objects.get(id=course_key)
            course = Course(
                course_id=course_key, display_name=course_overview.display_name
            )
        else:
            course = Course(course_id=course_key, display_name="")

        # May raise a permission denied
        self.check_object_permissions(self.request, course)

        return course

    def post(self, request, *args, **kwargs):
        """
        Return a guest token for accessing the Superset API.
        """
        course = self.get_object()

        built_in_filters = [
            f"org = '{course.course_id.org}'",
            f"course_name = '{course.display_name}'",
            f"course_run = '{course.course_id.run}'",
        ]
        dashboards = settings.ASPECTS_INSTRUCTOR_DASHBOARDS
        extra_filters_format = settings.SUPERSET_EXTRA_FILTERS_FORMAT

        guest_token, exception = generate_guest_token(
            user=request.user,
            course=course,
            dashboards=dashboards,
            filters=built_in_filters + extra_filters_format,
        )

        if not guest_token:
            raise ImproperlyConfigured(
                _(
                    "Unable to fetch Superset guest token, "
                    "mostly likely due to invalid settings.SUPERSET_CONFIG: {exception}"
                ).format(exception=exception)
            )

        return Response({"guestToken": guest_token})
