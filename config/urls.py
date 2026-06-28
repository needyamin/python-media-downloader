from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from downloader import views, admin_views

urlpatterns = [
    path('', views.index, name='index'),
    path('health/', csrf_exempt(views.health), name='health'),
    path('info/', csrf_exempt(views.get_info), name='info'),
    path('download/', csrf_exempt(views.download), name='download'),
    path('status/<str:task_id>/', views.job_status, name='job_status'),
    path('file/<str:task_id>/', views.serve_file, name='serve_file'),
    path('admin/', admin_views.admin_login, name='admin_login'),
    path('admin/panel/', admin_views.admin_panel, name='admin_panel'),
    path('admin/delete/', admin_views.admin_delete, name='admin_delete'),
    path('admin/delete-all/', admin_views.admin_delete_all, name='admin_delete_all'),
    path('admin/logout/', admin_views.admin_logout, name='admin_logout'),
]
