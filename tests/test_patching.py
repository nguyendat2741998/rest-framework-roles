import importlib
from unittest.mock import patch, MagicMock, Mock, call

import pytest
from django.urls import get_resolver, set_urlconf
from django.conf import settings
from rest_framework.test import APIRequestFactory

from .utils import UserSerializer, _func_name
from .fixtures import admin, user, anon
import patching


# ------------------------------------------------------------------------------


from rest_framework import routers, permissions, viewsets, views, decorators
import rest_framework as drf
from django.views.generic import ListView
import django
from django.contrib.auth.models import User
from django.urls import path, include
from django.http import HttpResponse

def django_function_view(request):
    return HttpResponse(_func_name())

@drf.decorators.api_view()
def rest_function_view(request):
    # This behaves exactly the same as if it was a method of APIView
    return HttpResponse(_func_name())

class DjangoView(django.views.generic.View):
    def not_a_view(self, *args, **kwargs):
        # Not a view since not the standard get, post, etc.
        return HttpResponse(_func_name())

class RestAPIView(drf.views.APIView, drf.mixins.ListModelMixin):  # This is the mother class of all classes
    serializer_class = UserSerializer
    permission_classes = (drf.permissions.IsAdminUser,)
    queryset = User.objects.all()

    @drf.decorators.action(detail=False)
    def custom_view(self):
        return HttpResponse(_func_name())

urlpatterns = [
    path('django_function_view', django_function_view),
    path('rest_function_view', rest_function_view),
    path('DjangoView', DjangoView.as_view()),
    path('RestAPIView', RestAPIView.as_view()),
]


# ------------------------------------------------------------------------------


def test_is_method_view():
    assert not patching.is_method_view(urlpatterns[0].callback)
    assert patching.is_method_view(urlpatterns[1].callback)
    assert patching.is_method_view(urlpatterns[2].callback)
    assert patching.is_method_view(urlpatterns[3].callback)


@pytest.mark.urls(__name__)
class TestPatch():
    """
    Ensure views are patched correctly regardless if they are functions or classes

    For classes we need to ensure that not the dispatch() method itself is patched
    but rather the view methods individually
    """

    def setup(self):
        patching.patch()  # Ensure patching occurs!
        self.urlconf = importlib.import_module(__name__)
        self.resolver = get_resolver(self.urlconf)

    def test_django_function_views_are_patched_directly(self):
        match = self.resolver.resolve('/django_function_view')
        assert match.func != django_function_view  # should point to wrapper
        match.func.__qualname__.startswith('function_view_wrapper')
        assert match.func.__module__ == 'patching'

    def test_rest_function_views_not_patched_directly(self):
        """
        REST function view are internally converted to methods so should be
        patched the same way as class-based views.
        """
        match = self.resolver.resolve('/rest_function_view')
        # We expect the 'view' to still point to dispatch
        assert match.func.__wrapped__.__wrapped__.__name__ == 'dispatch'

    def test_method_views_patching(self, client, admin):
        """
        Since class method views always point to dispatch, we need to call dispatch
        and ensure that it was routed to the view wrapper instead to the view method.

        Expected order of function chaining:

            dispatch -> get -> view wrapper -> view method
        """
        # After dispatch() request should be routed to the view wrapper instead
        # of directly calling the view method.

        # def mocked_class_view_wrapper(view):
        #     def wrapped():
        #     return patching.class
        # mocked_class_view_wrapper = MagicMock(return_value=)

        # Ensure wrapper is called before view
        # def mocked_before_view():
        #     print('Before view')
        # def mocked_view(request):
        #     print('view')
        #     return HttpResponse()

        match = self.resolver.resolve('/rest_function_view')
        request = APIRequestFactory().get('/rest_function_view')
        cls = match.func.view_class
        inst = cls()


        calls = []
        def mark_called_dispatch(*args):
            calls.append('dispatch')
        def mark_called_view_wrapper(*args):
            calls.append('view_wrapper')

        # Keep track of order the functions are called
        with patch.object(cls, 'dispatch', wraps=inst.dispatch) as mock_dispatch:
            mock_dispatch.side_effect = mark_called_dispatch
            with patch('patching.before_view') as mock_before_view:
                mock_before_view.side_effect = mark_called_view_wrapper
                # TODO: Test view was called after the view_wrapper

                response = match.func(request)
                assert response.status_code == 200
                assert response.content.decode() == 'rest_function_view'
                assert calls == ['dispatch', 'view_wrapper']

    # def test_DjangoListView(self):
    #     """
    #     Classes are a bit special since the view wrappers need to be applied on
    #     every view, and not the class callable with essentially is the dispatch()
    #     method. Aka patching must occur for each view
    #     """
    #     # Without patching
    #     match = self.resolver.resolve('/DjangoListView')
    #
    # # def test_RestAPIView(self):
    # #     match = self.resolver.resolve('/RestAPIView')
    # #     # Nothing before the dispatcher should be patched
    # #     assert match.func.__module__ != 'patching'
    # #     assert match.func.__name__ == 'RestAPIView'
    # #     assert match.func.__wrapped__.__wrapped__.__name__ == 'dispatch'
    # #     # All method views should be patched
    # #     # TODO: Ensure patching occurs on the vies..
    # #     """
    # #     Patching class methods strategy
    # #         1. We know which classes to patch.
    # #         2. Patch all methods of classes (except known parent methods which are
    # #            definetely not views) with a view-checker decorator.
    # #            method. It should call before_view in that case.
    # #         3. The decorator should check if the caller function is the dispatch. If
    # #            it is, then this should be a view and we therefore call before_view(view, ..)
    # #     """
    #     # assert
    #     # import IPython; IPython.embed(using=False)


def test_user_is_populated_inside_wrapper():
    """
    There is a huge difference between Django and REST when it comes to order of
    user population.

    In Django request.user is a lazy object and can thus be fetched at any point.
    However in REST, it is not so that can be a problem.
    """
    pass