# Copyright 2014 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for modules/dashboard/."""

__author__ = 'Glenn De Jonghe (gdejonghe@google.com)'

import cgi
import itertools
import time
import json

import actions
from common import crypto
from common.utils import Namespace
from models import courses
from models import models
from models import resources_display
from models import transforms
from models.custom_modules import Module
from models.roles import Permission
from models.roles import Roles
from modules.dashboard import dashboard
from common import menus
from modules.dashboard.dashboard import DashboardHandler
from modules.dashboard.question_group_editor import QuestionGroupRESTHandler
from modules.dashboard.role_editor import RoleRESTHandler

from google.appengine.api import namespace_manager

class QuestionTablesTests(actions.TestBase):
    def _soup_table(self):
        asset_tables = self.parse_html_string_to_soup(
            self.get(self.URL).body).select('.assets-table')
        self.assertEquals(len(asset_tables), 1)
        return asset_tables[0]

class QuestionDashboardTestCase(QuestionTablesTests):
    """Tests Assets > Questions."""
    COURSE_NAME = 'question_dashboard'
    ADMIN_EMAIL = 'admin@foo.com'
    URL = 'dashboard?action=edit_questions'

    def setUp(self):
        super(QuestionDashboardTestCase, self).setUp()

        actions.login(self.ADMIN_EMAIL, is_admin=True)
        self.base = '/' + self.COURSE_NAME
        context = actions.simple_add_course(
            self.COURSE_NAME, self.ADMIN_EMAIL, 'Questions Dashboard')
        self.old_namespace = namespace_manager.get_namespace()
        namespace_manager.set_namespace('ns_%s' % self.COURSE_NAME)

        self.course = courses.Course(None, context)

    def tearDown(self):
        namespace_manager.set_namespace(self.old_namespace)
        super(QuestionDashboardTestCase, self).tearDown()

    def test_unused_question(self):
        # Create an unused question
        unused_question_dto = models.QuestionDTO(None, {
            'description': 'unused',
            'type': 0
        })
        unused_question_id = models.QuestionDAO.save(unused_question_dto)
        self.course.save()

        dom = self.parse_html_string(self.get(self.URL).body)
        question_row = dom.find('.//tr[@data-quid=\'{}\']'.format(
            unused_question_id))
        filter_data = json.loads(question_row.get('data-filter'))
        self.assertEqual(filter_data['unused'], 1)

    def test_table_entries(self):
        # Create a question
        mc_question_description = 'Test MC Question'
        mc_question_dto = models.QuestionDTO(None, {
            'description': mc_question_description,
            'type': 0  # MC
        })
        mc_question_id = models.QuestionDAO.save(mc_question_dto)

        # Create an assessment and add the question to the content.
        # Also include a broken question ref to the assessment (and expect this
        # doesn't break anything).
        assessment_one = self.course.add_assessment()
        assessment_one.title = 'Test Assessment One'
        assessment_one.html_content = """
            <question quid="%s" weight="1" instanceid="1"></question>
            <question quid="broken" weight="1" instanceid="broken"></question>
        """ % mc_question_id

        # Create a second question
        sa_question_description = 'Test SA Question'
        sa_question_dto = models.QuestionDTO(None, {
            'description': sa_question_description,
            'type': 1  # SA
        })
        sa_question_id = models.QuestionDAO.save(sa_question_dto)

        # Create a question group and add the second question
        qg_description = 'Question Group'
        qg_dto = models.QuestionGroupDTO(None, {
              'description': qg_description,
             'items': [{'question': str(sa_question_id)}]
        })
        qg_id = models.QuestionGroupDAO.save(qg_dto)

        # Create a second assessment and add the question group to the content
        assessment_two = self.course.add_assessment()
        assessment_two.title = 'Test Assessment'
        assessment_two.html_content = """
            <question-group qgid="%s" instanceid="QG"></question-group>
        """ % qg_id

        self.course.save()

        # First check Question Bank table
        questions_table = self._soup_table()
        question_rows = questions_table.select('tr[data-filter]')
        self.assertEquals(len(question_rows), 2)

        # Check edit link and description of the first question
        first_row = question_rows[0]
        description_link = first_row.select('.description-cell a')[0]
        self.assertEquals(
            description_link.text.strip(), mc_question_description)
        self.assertEquals(description_link.get('href'), (
            'dashboard?action=edit_question&key={}'.format(mc_question_id)))

        # Check if the assessment is listed
        location_link = first_row.select('.locations-cell a')[0]
        self.assertEquals(location_link.get('href'),
            'assessment?name={}'.format(assessment_one.unit_id))
        self.assertEquals(assessment_one.title, location_link.text.strip())

        # Check second question (=row)
        second_row = question_rows[1]
        self.assertEquals(
            second_row.select('.description-cell a')[0].text.strip(),
            sa_question_description)
        # Check whether the containing Question Group is listed
        self.assertEquals(second_row.select('.groups-cell li')[0].text.strip(),
            qg_description)

    def test_no_questions(self):
        soup = self.parse_html_string_to_soup(self.get(self.URL).body)
        self.assertEquals(
            1, len(soup.select('.gcb-list__empty-message')))

    def test_no_question_groups(self):
        description = 'Question description'
        models.QuestionDAO.save(models.QuestionDTO(None, {
            'description': description
        }))

        table = self._soup_table()
        self.assertEquals(
            description, table.select('.description-cell a')[0].text.strip())

    def test_if_buttons_are_present(self):
        """Tests if all buttons are present.

            In the past it wasn't allowed to add a question group when there
            were no questions yet.
        """
        body = self.get(self.URL).body
        self.assertIn('Add Short Answer', body)
        self.assertIn('Add Multiple Choice', body)

    def test_last_modified_timestamp(self):
        begin_time = time.time()
        question_dto = models.QuestionDTO(None, {})
        models.QuestionDAO.save(question_dto)
        self.assertTrue((begin_time <= question_dto.last_modified) and (
            question_dto.last_modified <= time.time()))

        questions_table = self._soup_table()
        self.assertEquals(
            questions_table.select('[data-timestamp]')[0].get(
                'data-timestamp', ''),
            str(question_dto.last_modified)
        )

    def test_question_clone(self):
        # Add a question by just nailing it in to the datastore.
        mc_question_description = 'Test MC Question'
        mc_question_dto = models.QuestionDTO(None, {
            'description': mc_question_description,
            'type': 0  # MC
        })
        models.QuestionDAO.save(mc_question_dto)

        # On the assets -> questions page, clone the question.
        response = self.get(self.URL)
        soup = self.parse_html_string_to_soup(self.get(self.URL).body)
        clone_link = soup.select('.clone-question')[0]
        question_key = clone_link.get('data-key')
        xsrf_token = soup.select(
            '#question-table')[0].get('data-clone-question-token')
        self.post(
            'dashboard?action=clone_question',
            {
                'key': question_key,
                'xsrf_token': xsrf_token
            })
        response = self.get(self.URL)
        self.assertIn(mc_question_description + ' (clone)', response.body)

    def _call_add_to_question_group(self, qu_id, qg_id, weight, xsrf_token):
        return self.post('dashboard', {
            'action': 'add_to_question_group',
            'question_id': qu_id,
            'group_id': qg_id,
            'weight': weight,
            'xsrf_token': xsrf_token,
        }, True)

    def test_add_to_question_group(self):
        # Create a question
        question_description = 'Question'
        question_dto = models.QuestionDTO(None, {
            'description': question_description,
            'type': 0  # MC
        })
        question_id = models.QuestionDAO.save(question_dto)

        add_to_group_selector = '.add-question-to-group'

        # No groups are present so no add_to_group icon should be present
        self.assertEqual([], self._soup_table().select(add_to_group_selector))

        # Create a group
        qg_description = 'Question Group'
        qg_dto = models.QuestionGroupDTO(None, {
            'description': qg_description,
            'items': []
        })
        qg_id = models.QuestionGroupDAO.save(qg_dto)

        # Since we now have a group, the add_to_group icon should be visible
        self.assertIsNotNone(
            self._soup_table().select(add_to_group_selector))

        # Add Question to Question Group via post_add_to_question_group
        questions_table = self._soup_table()
        xsrf_token = questions_table.get('data-qg-xsrf-token', '')
        response = self._call_add_to_question_group(
            question_id, qg_id, 1, xsrf_token)

        # Check if operation was successful
        self.assertEquals(response.status_int, 200)
        questions_table = self._soup_table()
        self.assertEquals(
            questions_table.select('.groups-cell li')[0].text.strip(),
            qg_description
        )

        # Check a bunch of calls that should fail
        response = self._call_add_to_question_group(question_id, qg_id, 1, 'a')
        self.assertEquals(response.status_int, 403)

        response = transforms.loads(self._call_add_to_question_group(
            -1, qg_id, 1, xsrf_token).body)
        self.assertEquals(response['status'], 500)

        response = transforms.loads(self._call_add_to_question_group(
            question_id, -1, 1, xsrf_token).body)
        self.assertEquals(response['status'], 500)

        response = transforms.loads(self._call_add_to_question_group(
            'a', qg_id, 1, xsrf_token).body)
        self.assertEquals(response['status'], 500)

        response = transforms.loads(self._call_add_to_question_group(
            question_id, qg_id, 'a', xsrf_token).body)
        self.assertEquals(response['status'], 500)


class QuestionGroupDashboardTestCase(QuestionTablesTests):
    """Tests Assets > Question Groups."""
    COURSE_NAME = 'question_group_dashboard'
    ADMIN_EMAIL = 'admin@foo.com'
    URL = 'dashboard?action=edit_question_groups'

    def setUp(self):
        super(QuestionGroupDashboardTestCase, self).setUp()

        actions.login(self.ADMIN_EMAIL, is_admin=True)
        self.base = '/' + self.COURSE_NAME
        context = actions.simple_add_course(
            self.COURSE_NAME, self.ADMIN_EMAIL, 'Question Groups Dashboard')
        self.old_namespace = namespace_manager.get_namespace()
        namespace_manager.set_namespace('ns_%s' % self.COURSE_NAME)

        self.course = courses.Course(None, context)

    def tearDown(self):
        namespace_manager.set_namespace(self.old_namespace)
        super(QuestionGroupDashboardTestCase, self).tearDown()

    def test_table_entries(self):
        # Create a question
        mc_question_description = 'Test MC Question'
        mc_question_dto = models.QuestionDTO(None, {
            'description': mc_question_description,
            'type': 0  # MC
        })
        mc_question_id = models.QuestionDAO.save(mc_question_dto)

        # Create a question group and add the question
        qg_description = 'Question Group'
        qg_dto = models.QuestionGroupDTO(None, {
              'description': qg_description,
             'items': [{'question': str(mc_question_id)}]
        })
        qg_id = models.QuestionGroupDAO.save(qg_dto)

        # Create a second assessment and add the question group to the content
        assessment_two = self.course.add_assessment()
        assessment_two.title = 'Test Assessment'
        assessment_two.html_content = """
            <question-group qgid="%s" instanceid="QG"></question-group>
        """ % qg_id

        self.course.save()

        # Check Question Group table
        question_groups_table = self._soup_table()
        row = question_groups_table.select('tbody tr')[0]
        # Check edit link and description
        edit_link = row.select('.description-cell a')[0]
        self.assertEquals(edit_link.text.strip(), qg_description)
        self.assertEquals(
            edit_link.get('href'),
            'dashboard?action=edit_question_group&key={}'.format(qg_id))

        # The question that is part of this group, should be listed
        self.assertEquals(
            row.select('.questions-cell li')[0].text.strip(),
            mc_question_description)

        # Assessment where this Question Group is located, should be linked
        location_link = row.select('.locations-cell a')[0]
        self.assertEquals(
            location_link.get('href'),
            'assessment?name={}'.format(assessment_two.unit_id))
        self.assertEquals(assessment_two.title, location_link.text.strip())

    def test_no_question_groups(self):
        soup = self.parse_html_string_to_soup(self.get(self.URL).body)
        self.assertEquals(
            1, len(soup.select('.gcb-list__empty-message')))

    def test_no_questions(self):
        description = 'Group description'
        models.QuestionGroupDAO.save(models.QuestionGroupDTO(None, {
                    'description': description
        }))
        question_groups_table = self._soup_table()
        self.assertEquals(
            question_groups_table.select('.description-cell a')[0].text.strip(),
            description)

    def test_if_buttons_are_present(self):
        """Tests if all buttons are present.

            In the past it wasn't allowed to add a question group when there
            were no questions yet.
        """
        body = self.get(self.URL).body
        self.assertIn('Add Question Group', body)

    def test_adding_empty_question_group(self):
        QG_URL = '/%s%s' % (self.COURSE_NAME, QuestionGroupRESTHandler.URI)
        xsrf_token = crypto.XsrfTokenManager.create_xsrf_token(
            QuestionGroupRESTHandler.XSRF_TOKEN)
        description = 'Question Group'
        payload = {
            'description': description,
            'version': QuestionGroupRESTHandler.SCHEMA_VERSIONS[0],
            'introduction': '',
            'items': []
        }
        response = self.put(QG_URL, {'request': transforms.dumps({
            'xsrf_token': cgi.escape(xsrf_token),
            'payload': transforms.dumps(payload)})})
        self.assertEquals(response.status_int, 200)
        payload = transforms.loads(response.body)
        self.assertEquals(payload['status'], 200)
        self.assertEquals(payload['message'], 'Saved.')
        question_groups_table = self._soup_table()
        self.assertEquals(
            question_groups_table.select('.description-cell a')[0].text.strip(),
            description)

    def test_last_modified_timestamp(self):
        begin_time = time.time()
        qg_dto = models.QuestionGroupDTO(None, {})
        models.QuestionGroupDAO.save(qg_dto)
        self.assertTrue((begin_time <= qg_dto.last_modified) and (
            qg_dto.last_modified <= time.time()))

        question_groups_table = self._soup_table()
        self.assertEquals(
            question_groups_table.select('[data-timestamp]')[0].get(
                'data-timestamp', ''),
            str(qg_dto.last_modified)
        )

    def _call_add_to_question_group(self, qu_id, qg_id, weight, xsrf_token):
        return self.post('dashboard', {
            'action': 'add_to_question_group',
            'question_id': qu_id,
            'group_id': qg_id,
            'weight': weight,
            'xsrf_token': xsrf_token,
        }, True)

    # TODO(tlarsen): add Question Group tests; tracked here: http://b/24373601

class CourseOutlineTestCase(actions.CourseOutlineTest):
    """Tests the Course Outline."""
    COURSE_NAME = 'outline'
    ADMIN_EMAIL = 'admin@foo.com'
    STUDENT_EMAIL = 'user@foo.com'
    URL = 'dashboard'

    def setUp(self):
        super(CourseOutlineTestCase, self).setUp()

        actions.login(self.ADMIN_EMAIL, is_admin=True)
        self.base = '/' + self.COURSE_NAME
        context = actions.simple_add_course(
            self.COURSE_NAME, self.ADMIN_EMAIL, 'Outline Testing')

        self.course = courses.Course(None, context)
        self.assessment = self.course.add_assessment()
        self.assessment.title = 'Test Assessment'
        self.link = self.course.add_link()
        self.link.title = 'Test Link'
        self.unit = self.course.add_unit()
        self.unit.title = 'Test Unit'
        self.lesson = self.course.add_lesson(self.unit)
        self.lesson.title = 'Test Lesson'
        self.course.save()

    def _check_private_setting(self, soup, component_type, key, is_private):
        lock = soup.select('[data-key="{}"]'.format(key))[0]
        self.assertEqual(lock.get('data-component-type'), component_type)
        self.assertAvailabilityState(lock, available=not is_private)

    def _get_item_for(self, component_type, item_id):
        return self._get_outline().select('[data-{}-id={}]'.format(
            component_type, item_id))[0]

    def _get_outline(self):
        response = self.get(self.URL)
        return self.parse_html_string_to_soup(response.body).select(
            '.course-outline')[0]

    def _check_syllabus_for_admin(self, private, title):
        response = self.get('/%s/course' % self.COURSE_NAME)
        dom = self.parse_html_string(response.body)
        units = dom.findall('.//div[@id="gcb-main"]//li')
        for unit in units:
            text = ' '.join(''.join(unit.itertext()).split())
            if title in text:
                if private:
                    self.assertIn('(Private)', text)
                else:
                    self.assertNotIn('(Private)', text)

    def _check_syllabus_for_student(self, private, shown, title):
        actions.login(self.STUDENT_EMAIL, is_admin=False)
        response = self.get('/%s/course' % self.COURSE_NAME)
        dom = self.parse_html_string(response.body)
        units = dom.findall('.//div[@id="gcb-main"]//li')

        found = False
        for unit in units:
            text = ' '.join(''.join(unit.itertext()).split())
            if title in text:
                found = True
                if private:
                    if shown:
                        self.assertIsNone(unit.find('.//a'))
                    else:
                        self.fail('private hidden items should not be found.')
                else:
                    self.assertIsNotNone(unit.find('.//a'))

        if private and not shown:
            self.assertFalse(found)
        actions.login(self.ADMIN_EMAIL, is_admin=True)

    def test_setting_combinations(self):
        cases = ((self.unit, 'unit',),
                 (self.link, 'link'),
                 (self.assessment, 'assessment'))
        for unit, kind in cases:
            for private, shown in itertools.product([True, False], repeat=2):
                unit.now_available = not private
                unit.shown_when_unavailable = shown
                self.course.save()
                soup = self._get_outline()
                self._check_private_setting(soup, kind, unit.unit_id, private)
                self._check_syllabus_for_admin(private, unit.title)
                self._check_syllabus_for_student(private, shown, unit.title)

    def test_lesson_public_private(self):
        self.lesson.now_available = True
        self.course.save()

        self._check_private_setting(
            self._get_outline(), 'lesson', self.lesson.lesson_id, False)

        self.lesson.now_available = False
        self.course.save()
        self._check_private_setting(
            self._get_outline(), 'lesson', self.lesson.lesson_id, True)

    def _check_item_label(self, li, student_url, title):
        a = li.select('.name a')[0]
        self.assertEquals(a.text, title)
        self.assertEquals(
            li.select('.view-icon')[0].get('href', ''), student_url)

    def test_title(self):
        self._check_item_label(
            self._get_item_for('unit', self.link.unit_id), '',
            self.link.title)

        self._check_item_label(
            self._get_item_for('unit', self.assessment.unit_id),
            'assessment?name={}'.format(self.assessment.unit_id),
            self.assessment.title)

        self._check_item_label(
            self._get_item_for('unit', self.unit.unit_id),
            'unit?unit={}'.format(self.unit.unit_id), self.unit.title)

        self._check_item_label(
            self._get_item_for('lesson', self.lesson.lesson_id),
            'unit?unit={}&lesson={}'.format(
                self.unit.unit_id, self.lesson.lesson_id),
            self.lesson.title)


class RoleEditorTestCase(actions.TestBase):
    """Tests the Roles tab and Role Editor."""
    COURSE_NAME = 'role_editor'
    ADMIN_EMAIL = 'admin@foo.com'
    URL = 'dashboard?action=edit_roles'

    def setUp(self):
        super(RoleEditorTestCase, self).setUp()

        actions.login(self.ADMIN_EMAIL, is_admin=True)
        self.base = '/' + self.COURSE_NAME
        context = actions.simple_add_course(
            self.COURSE_NAME, self.ADMIN_EMAIL, 'Roles Testing')

        self.course = courses.Course(None, context)

        self.old_namespace = namespace_manager.get_namespace()
        namespace_manager.set_namespace('ns_%s' % self.COURSE_NAME)

        self.old_registered_permission = Roles._REGISTERED_PERMISSIONS
        Roles._REGISTERED_PERMISSIONS = {}

    def tearDown(self):
        Roles._REGISTERED_PERMISSIONS = self.old_registered_permission
        namespace_manager.set_namespace(self.old_namespace)
        super(RoleEditorTestCase, self).tearDown()

    def _create_role(self, role):
        role_dto = models.RoleDTO(None, {
            'name': role,
        })
        return models.RoleDAO.save(role_dto)

    def test_roles_tab(self):
        role_name = 'Test Role'
        role_id = self._create_role(role_name)
        li = self.parse_html_string(self.get(self.URL).body).find(
            './/tbody/tr/td/a')
        self.assertEquals(li.text.strip(), role_name)
        self.assertEquals(li.get('href'), (
            'dashboard?action=edit_role&key=%s' % role_id))

    def test_editor_hooks(self):
        module1 = Module('module1', '', [], [])
        module2 = Module('module2', '', [], [])
        module3 = Module('module3', '', [], [])
        module4 = Module('module4', '', [], [])
        Roles.register_permissions(module1, lambda unused: [
            Permission('permissiona', 'a'), Permission('permissionb', 'b')])

        Roles.register_permissions(module2, lambda unused: [
            Permission('permissionc', 'c'), Permission('permissiond', 'd')])
        Roles.register_permissions(module4, lambda unused: [
            Permission('permissiong', 'g'), Permission('permissiond', 'h')])
        handler = RoleRESTHandler()
        handler.course = self.course

        datastore_permissions = {
            module1.name: ['permission', 'permissiona', 'permissionb'],
            module2.name: ['permissionc', 'permissiond'],
            module3.name: ['permissione', 'permissionf']
        }
        datastore_dict = {
            'name': 'Role Name',
            'users': ['test@test.com', 'test2@test.com'],
            'permissions': datastore_permissions
        }
        editor_dict = handler.transform_for_editor_hook(datastore_dict)
        self.assertEquals(editor_dict['name'], 'Role Name')
        self.assertEquals(editor_dict['users'], 'test@test.com, test2@test.com')
        modules = editor_dict['modules']
        # Test registered assigned permission
        permissionc = modules[module2.name][0]
        self.assertEquals(permissionc['assigned'], True)
        self.assertEquals(permissionc['name'], 'permissionc')
        self.assertEquals(permissionc['description'], 'c')
        # Test unregistered module with assigned permission
        permissionsf = modules[RoleRESTHandler.INACTIVE_MODULES][1]
        self.assertEquals(permissionsf['assigned'], True)
        self.assertEquals(permissionsf['name'], 'permissionf')
        self.assertEquals(
            permissionsf['description'],
            'This permission was set by the module "module3" which is '
            'currently not registered.'
        )
        # Test registered module with assigned unregistered permission
        permission = modules[module1.name][2]
        self.assertEquals(permission['assigned'], True)
        self.assertEquals(permission['name'], 'permission')
        self.assertEquals(
            permission['description'],
            'This permission is currently not registered.'
        )
        # Test registered unassigned permissions
        permissiong = editor_dict['modules'][module4.name][0]
        self.assertEquals(permissiong['assigned'], False)
        self.assertEquals(permissiong['name'], 'permissiong')
        self.assertEquals(permissiong['description'], 'g')
        # Call the hook which gets called when saving
        new_datastore_dict = handler.transform_after_editor_hook(datastore_dict)
        # If original dict matches new dict then both hooks work correctly
        self.assertEquals(datastore_dict, new_datastore_dict)

    def test_not_unique_role_name(self):
        role_name = 'Test Role'
        role_id = self._create_role(role_name)
        handler = RoleRESTHandler()
        handler.course = self.course
        editor_dict = {
            'name': role_name
        }
        errors = []
        handler.validate(editor_dict, role_id + 1, None, errors)
        self.assertEquals(
            errors[0], 'The role must have a unique non-empty name.')


class DashboardAccessTestCase(actions.TestBase):
    ACCESS_COURSE_NAME = 'dashboard_access_yes'
    NO_ACCESS_COURSE_NAME = 'dashboard_access_no'
    ADMIN_EMAIL = 'admin@foo.com'
    USER_EMAIL = 'user@foo.com'
    ROLE = 'test_role'
    ACTION = 'test_action'
    PERMISSION = 'can_access_dashboard'
    PERMISSION_DESCRIPTION = 'Can Access Dashboard.'

    def setUp(self):
        super(DashboardAccessTestCase, self).setUp()
        actions.login(self.ADMIN_EMAIL, is_admin=True)

        context = actions.simple_add_course(
            self.ACCESS_COURSE_NAME, self.ADMIN_EMAIL, 'Course with access')

        self.course_with_access = courses.Course(None, context)

        with Namespace(self.course_with_access.app_context.namespace):
            role_dto = models.RoleDTO(None, {
                'name': self.ROLE,
                'users': [self.USER_EMAIL],
                'permissions': {dashboard.custom_module.name: [self.PERMISSION]}
            })
            models.RoleDAO.save(role_dto)

        context = actions.simple_add_course(
            self.NO_ACCESS_COURSE_NAME, self.ADMIN_EMAIL,
            'Course with no access'
        )

        self.course_without_access = courses.Course(None, context)

        def test_content(self):
            return self.render_page(
                {'main_content': 'test', 'page_title': 'test'})

        # save properties
        self.old_menu_group = DashboardHandler.root_menu_group
        # pylint: disable=W0212
        self.old_get_acitons = DashboardHandler._custom_get_actions
        # pylint: enable=W0212

        # put a dummy method in
        menu_group = menus.MenuGroup('test', 'Test Dashboard')
        DashboardHandler.root_menu_group = menu_group
        DashboardHandler.default_action = self.ACTION
        DashboardHandler.add_nav_mapping(self.ACTION, self.ACTION)
        DashboardHandler.add_sub_nav_mapping(self.ACTION, self.ACTION,
            self.ACTION, action=self.ACTION, contents=test_content)
        DashboardHandler.map_get_action_to_permission(
            self.ACTION, dashboard.custom_module, self.PERMISSION)
        actions.logout()

    def tearDown(self):
        # restore properties
        # pylint: disable=W0212
        DashboardHandler.root_menu_group = self.old_menu_group
        DashboardHandler._custom_get_actions = self.old_get_acitons
        # pylint: enable=W0212

        super(DashboardAccessTestCase, self).tearDown()

    def test_dashboard_access_method(self):
        with Namespace(self.course_with_access.app_context.namespace):
            self.assertFalse(DashboardHandler.current_user_has_access(
                self.course_with_access.app_context))
        with Namespace(self.course_without_access.app_context.namespace):
            self.assertFalse(DashboardHandler.current_user_has_access(
                self.course_without_access.app_context))
        actions.login(self.USER_EMAIL, is_admin=False)
        with Namespace(self.course_with_access.app_context.namespace):
            self.assertTrue(DashboardHandler.current_user_has_access(
                self.course_with_access.app_context))
        with Namespace(self.course_without_access.app_context.namespace):
            self.assertFalse(DashboardHandler.current_user_has_access(
                self.course_without_access.app_context))
        actions.logout()

    def _get_all_picker_options(self):
        return self.parse_html_string(
            self.get('/%s/dashboard' % self.ACCESS_COURSE_NAME).body
        ).findall('.//*[@id="gcb-course-picker-menu"]//a')

    def test_course_picker(self):
        actions.login(self.USER_EMAIL, is_admin=False)
        picker_options = self._get_all_picker_options()
        self.assertEquals(len(list(picker_options)), 1)
        actions.logout()

        actions.login(self.ADMIN_EMAIL, is_admin=True)
        picker_options = self._get_all_picker_options()
        # Expect 3 courses, as the default one is also considered for the picker
        self.assertEquals(len(picker_options), 3)
        actions.logout()

    def _get_right_nav_links(self):
        return self.parse_html_string(
            self.get('/%s/' % self.ACCESS_COURSE_NAME).body
        ).findall(
            './/div[@id="gcb-nav-x"]/div/ul/li[@class="gcb-pull-right"]')

    def test_dashboard_link(self):
        # Not signed in => no dashboard or admin link visible
        self.assertEquals(len(self._get_right_nav_links()), 0)
        # Sign in user with dashboard permissions => dashboard link visible
        actions.login(self.USER_EMAIL, is_admin=False)
        links = self._get_right_nav_links()
        self.assertEquals(len(links), 1)
        self.assertEquals(links[0].find('a').get('href'), 'dashboard')
        self.assertEquals(links[0].find('a').text, 'Dashboard')
        # Sign in course admin => dashboard link visible
        actions.login(self.ADMIN_EMAIL, is_admin=False)
        links = self._get_right_nav_links()
        self.assertEquals(len(links), 1)
        self.assertEquals(links[0].find('a').get('href'), 'dashboard')
        self.assertEquals(links[0].find('a').text, 'Dashboard')


class DashboardCustomNavTestCase(actions.TestBase):
    """Tests Assets > Questions."""
    COURSE_NAME = 'custom_dashboard'
    ADMIN_EMAIL = 'admin@foo.com'
    URL = 'dashboard?action=custom_mod'
    ACTION = 'custom_mod'
    CONTENT_PATH = './/div[@id="gcb-main-area"]/div[@id="gcb-main-content"]'

    def setUp(self):
        super(DashboardCustomNavTestCase, self).setUp()

        actions.login(self.ADMIN_EMAIL, is_admin=True)
        self.base = '/' + self.COURSE_NAME
        context = actions.simple_add_course(
            self.COURSE_NAME, self.ADMIN_EMAIL, 'Custom Dashboard')
        self.old_namespace = namespace_manager.get_namespace()
        namespace_manager.set_namespace('ns_%s' % self.COURSE_NAME)

        self.course = courses.Course(None, context)

    def tearDown(self):
        namespace_manager.set_namespace(self.old_namespace)
        super(DashboardCustomNavTestCase, self).tearDown()

    def test_custom_top_nav(self):
        # Add a new top level navigation action
        DashboardHandler.add_nav_mapping(self.ACTION, 'CUSTOM_MOD')

        class CustomNavHandler(object):

            @classmethod
            def show_page(cls, dashboard_handler):
                dashboard_handler.render_page({
                    'page_title': dashboard_handler.format_title('CustomNav'),
                    'main_content': 'MainContent'})
        DashboardHandler.add_custom_get_action(
            self.ACTION, CustomNavHandler.show_page)

        dom = self.parse_html_string(self.get('dashboard').body)
        selected_nav_path = ('.//tr[@class="gcb-nav-bar-level-1"]'
                             '//a[@class="selected"]')
        self.assertEquals('Edit', dom.find(selected_nav_path).text)
        dom = self.parse_html_string(self.get(self.URL).body)

        self.assertEquals('CUSTOM_MOD', dom.find(selected_nav_path).text)
        self.assertEquals(
            'MainContent', dom.find(self.CONTENT_PATH).text.strip())

        DashboardHandler.remove_custom_get_action(self.ACTION)

        # Add a new tab under the new navigation action
        class CustomTabHandler(object):

            @classmethod
            def display_html(cls, unused_dashboard_handler):
                return 'MainTabContent'

        dashboard.DashboardHandler.add_sub_nav_mapping(
            self.ACTION, 'cu_tab', 'CustomTab', action=self.ACTION,
            contents=CustomTabHandler)
        dom = self.parse_html_string(self.get(self.URL).body)
        self.assertEquals('CUSTOM_MOD', dom.find(selected_nav_path).text)
        self.assertEquals(
            'MainTabContent', dom.find(self.CONTENT_PATH).text.strip())

        selected_tab_path = ('.//*[@class="gcb-nav-bar-level-2"]'
                             '//a[@class="selected"]')
        self.assertEquals('CustomTab', dom.find(selected_tab_path).text)

    def test_first_tab(self):
        url = 'dashboard?action=analytics_students'
        dom = self.parse_html_string(self.get(url).body)
        selected_tab_path = ('.//*[@class="gcb-nav-bar-level-2"]'
                             '//a[@class="selected"]')
        self.assertEquals('Students', dom.find(selected_tab_path).text)


class TestLessonSchema(actions.TestBase):

    COURSE_NAME = 'lesson_dashboard'
    ADMIN_EMAIL = 'admin@foo.com'

    def setUp(self):
        super(TestLessonSchema, self).setUp()
        actions.login(self.ADMIN_EMAIL, is_admin=True)
        context = actions.simple_add_course(
            self.COURSE_NAME, self.ADMIN_EMAIL, 'Lesson Course')
        self.old_namespace = namespace_manager.get_namespace()
        namespace_manager.set_namespace('ns_%s' % self.COURSE_NAME)

        self.course = courses.Course(None, context)
        self.unit = self.course.add_unit()
        self.course.save()

    def tearDown(self):
        namespace_manager.set_namespace(self.old_namespace)
        super(TestLessonSchema, self).tearDown()

    def test_video_field_hidden_in_new_lessons(self):
        lesson = self.course.add_lesson(self.unit)
        self.course.save()

        schema = get_lesson_schema(self.course, lesson)
        video_options = find_schema_field(schema, ['properties', 'video',
            '_inputex'])
        self.assertEqual(video_options['_type'], 'hidden')

    def test_video_field_not_hidden_in_lessons_with_field_set(self):
        lesson = self.course.add_lesson(self.unit)
        lesson.video = 'oHg5SJYRHA0'
        self.course.save()

        schema = get_lesson_schema(self.course, lesson)
        video_options = find_schema_field(schema, ['properties', 'video',
            '_inputex'])
        self.assertNotEqual(video_options.get('_type'), 'hidden')

def get_lesson_schema(course, lesson):
    return resources_display.ResourceLesson.get_schema(
        course, lesson.lesson_id).get_schema_dict()

def find_schema_field(schema, key):
    for field, options in schema:
        if field == key:
            return options
