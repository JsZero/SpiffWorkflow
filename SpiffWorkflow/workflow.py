# -*- coding: utf-8 -*-
from __future__ import division, absolute_import
from __future__ import print_function

import copy
from builtins import next
from builtins import object
# Copyright (C) 2007 Samuel Abels
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301  USA
import logging
from . import specs
from .task import Task
from .util.compat import mutex
from .util.event import Event
from .exceptions import WorkflowException
from .bpmn.specs.BoundaryEvent import _BoundaryEventParent
LOG = logging.getLogger(__name__)



class Workflow(object):

    """
    The engine that executes a workflow.
    It is a essentially a facility for managing all branches.
    A Workflow is also the place that holds the data of a running workflow.
    """

    def __init__(self, workflow_spec, deserializing=False, **kwargs):
        """
        Constructor.

        :type workflow_spec: specs.WorkflowSpec
        :param workflow_spec: The workflow specification.
        :type deserializing: bool
        :param deserializing: set to true when deserializing to avoid
          generating tasks twice (and associated problems with multiple
          hierarchies of tasks)
        """
        assert workflow_spec is not None
        LOG.debug("__init__ Workflow instance: %s" % self.__str__())
        self.spec = workflow_spec
        self.data = {}
        self.outer_workflow = kwargs.get('parent', self)
        self.locks = {}
        self.last_task = None
        if deserializing:
            assert 'Root' in workflow_spec.task_specs
            root = workflow_spec.task_specs['Root']  # Probably deserialized
        else:
            if 'Root' in workflow_spec.task_specs:
                root = workflow_spec.task_specs['Root']
            else:
                root = specs.Simple(workflow_spec, 'Root')
        self.task_tree = Task(self, root)
        self.success = True
        self.debug = False

        # Events.
        self.completed_event = Event()

        # Prevent the root task from being executed.
        self.task_tree.state = Task.COMPLETED
        start = self.task_tree._add_child(self.spec.start, state=Task.FUTURE)

        self.spec.start._predict(start)
        if 'parent' not in kwargs:
            start.task_spec._update(start)

        self.task_mapping = self._get_task_mapping()
        # start.dump()

    def is_completed(self):
        """
        Returns True if the entire Workflow is completed, False otherwise.

        :rtype: bool
        :return: Whether the workflow is completed.
        """
        mask = Task.NOT_FINISHED_MASK
        iter = Task.Iterator(self.task_tree, mask)
        try:
            nexttask = next(iter)
        except StopIteration:
            # No waiting tasks found.
            return True
        return False

    def _get_waiting_tasks(self):
        waiting = Task.Iterator(self.task_tree, Task.WAITING)
        return [w for w in waiting]

    def _task_completed_notify(self, task):
        if task.get_name() == 'End':
            self.data.update(task.data)
        # Update the state of every WAITING task.
        for thetask in self._get_waiting_tasks():
            thetask.task_spec._update(thetask)
        if self.completed_event.n_subscribers() == 0:
            # Since is_completed() is expensive it makes sense to bail
            # out if calling it is not necessary.
            return
        if self.is_completed():
            self.completed_event(self)

    def _get_mutex(self, name):
        if name not in self.locks:
            self.locks[name] = mutex()
        return self.locks[name]

    def _get_task_mapping(self):
        task_mapping = {}
        for task in self.task_tree:
            thread_task_mapping = task_mapping.get(task.thread_id, {})
            tasks = thread_task_mapping.get(task.task_spec, set())
            tasks.add(task)
            thread_task_mapping[task.task_spec] = tasks
            task_mapping[task.thread_id] = thread_task_mapping
        return task_mapping

    def update_task_mapping(self):
        """
        Update the task_mapping of workflow, make sure the method is called
        every time you reconstruct task instance.
        """
        self.task_mapping = self._get_task_mapping()

    def set_data(self, **kwargs):
        """
        Defines the given attribute/value pairs.
        """
        self.data.update(kwargs)

    def get_data(self, name, default=None):
        """
        Returns the value of the data field with the given name, or the given
        default value if the data field does not exist.

        :type  name: str
        :param name: A data field name.
        :type  default: obj
        :param default: Return this value if the data field does not exist.
        :rtype:  obj
        :returns: The value of the data field.
        """
        return self.data.get(name, default)

    def cancel(self, success=False):
        """
        Cancels all open tasks in the workflow.

        :type  success: bool
        :param success: Whether the Workflow should be marked as successfully
                        completed.
        """
        self.success = success
        cancel = []
        mask = Task.NOT_FINISHED_MASK
        for task in Task.Iterator(self.task_tree, mask):
            cancel.append(task)
        for task in cancel:
            task.cancel()

    def get_task_spec_from_name(self, name):
        """
        Returns the task spec with the given name.

        :type  name: str
        :param name: The name of the task.
        :rtype:  TaskSpec
        :returns: The task spec with the given name.
        """
        return self.spec.get_task_spec_from_name(name)

    def get_task(self, id,tasklist=None):
        """
        Returns the task with the given id.

        :type id:integer
        :param id: The id of a task.
        :param tasklist: Optional cache of get_tasks for operations
                         where we are calling multiple times as when we
                         are deserializing the workflow
        :rtype: Task
        :returns: The task with the given id.
        """
        if tasklist:
            tasks = [task for task in tasklist if task.id == id]
        else:
            tasks = [task for task in self.get_tasks() if task.id == id]
        return tasks[0] if len(tasks) == 1 else None

    def get_tasks_from_spec_name(self, name):
        """
        Returns all tasks whose spec has the given name.

        :type name: str
        :param name: The name of a task spec.
        :rtype: list[Task]
        :returns: A list of tasks that relate to the spec with the given name.
        """
        return [task for task in self.get_tasks_iterator()
                if task.task_spec.name == name]

    def empty(self,str):
        if str == None:
            return True
        if str == '':
            return True
        return False

    def get_message_name_xlate(self):
        message_name_xlate = {}

        alltasks = self.get_tasks()
        tasks = [x for x in alltasks if (x.state == x.READY or x.state== x.WAITING or x.state==x.COMPLETED)
                 and hasattr(x.parent,'task_spec')]
        #tasks = self.get_tasks(state=Task.READY)

        for task in tasks:
            parent = task.parent
            if hasattr(task.task_spec,'event_definition') \
                and hasattr(task.task_spec.event_definition,'message'):
                message_name_xlate[task.task_spec.event_definition.name] = task.task_spec.event_definition.message
            if isinstance(parent.task_spec,_BoundaryEventParent):
                for sibling in parent.children:
                    if hasattr(sibling.task_spec,'event_definition') \
                       and sibling.task_spec.event_definition is not None:
                        message_name_xlate[sibling.task_spec.event_definition.name] = \
                            sibling.task_spec.event_definition.message
                        # doing this for the case that we have triggered the event and it is now completed
                        # but the task is still active, so we would like to be able to re-trigger the event
                        if sibling.state == Task.COMPLETED and task.state == Task.READY:
                            sibling._setstate(Task.WAITING, force=True)
        return message_name_xlate

    def message(self,message_name,payload,resultVar):

        message_name_xlate = self.get_message_name_xlate()

        if message_name in message_name_xlate.keys() or \
            message_name in message_name_xlate.values():
            if message_name in message_name_xlate.keys():
                message_name = message_name_xlate[message_name]
            self.task_tree.internal_data['messages'] = self.task_tree.internal_data.get('messages',{}) # ensure
            self.task_tree.internal_data['messages'][message_name] = (payload,resultVar)
        self.refresh_waiting_tasks()
        self.do_engine_steps()
        self.task_tree.internal_data['messages'] = {}

    def signal(self, message_name):
        # breakpoint()
        message_name_xlate = self.get_message_name_xlate()

        if message_name in message_name_xlate.keys() or \
            message_name in message_name_xlate.values():
            if message_name in message_name_xlate.keys():
                message_name = message_name_xlate[message_name]
            self.task_tree.internal_data['signals'] = self.task_tree.internal_data.get('signals',{}) # ensure
            self.task_tree.internal_data['signals'][message_name] = True
        LOG.debug("signal Workflow instance: %s" % self.task_tree.internal_data)
        self.refresh_waiting_tasks()
        LOG.debug("signal Workflow instance: %s" % self.task_tree.internal_data)
        self.do_engine_steps()
        self.task_tree.internal_data['signals'] = {}

    def cancel_notify(self):
        self.task_tree.internal_data['cancels'] = \
                self.task_tree.internal_data.get('cancels', {})  # ensure
        self.task_tree.internal_data['cancels']['TokenReset'] = True
        self.refresh_waiting_tasks()
        self.do_engine_steps()
        self.task_tree.internal_data['cancels'] = {}

    def get_flat_nav_list(self):
        """Returns a navigation list with indentation hints, but the list
        is completly flat, and a nav item has no children."""
        from . import navigation
        return navigation.get_flat_nav_list(self)

    def get_deep_nav_list(self):
        """Returns a nested navigation list, where indentation hints are
        applied to recreate a deep structure."""
        from . import navigation
        return navigation.get_deep_nav_list(self)


    def get_tasks(self, state=Task.ANY_MASK):
        """
        Returns a list of Task objects with the given state.

        :type  state: integer
        :param state: A bitmask of states.
        :rtype:  list[Task]
        :returns: A list of tasks.
        """
        return [t for t in Task.Iterator(self.task_tree, state)]

    def reset_task_from_id(self, task_id):
        """
        Runs the task with the given id.

        :type  task_id: integer
        :param task_id: The id of the Task object.
        """
        if task_id is None:
            raise WorkflowException(self.spec, 'task_id is None')
        for task in self.task_tree:
            if task.id == task_id:
                return task.reset_token()
        msg = 'A task with the given task_id (%s) was not found' % task_id
        raise WorkflowException(self.spec, msg)

    def get_tasks_iterator(self, state=Task.ANY_MASK):
        """
        Returns a iterator of Task objects with the given state.

        :type  state: integer
        :param state: A bitmask of states.
        :rtype:  Task.Iterator
        :returns: A list of tasks.
        """
        return Task.Iterator(self.task_tree, state)

    def complete_task_from_id(self, task_id):
        """
        Runs the task with the given id.

        :type  task_id: integer
        :param task_id: The id of the Task object.
        """
        if task_id is None:
            raise WorkflowException(self.spec, 'task_id is None')
        for task in self.task_tree:
            if task.id == task_id:
                return task.complete()
        msg = 'A task with the given task_id (%s) was not found' % task_id
        raise WorkflowException(self.spec, msg)

    def complete_next(self, pick_up=True, halt_on_manual=True):
        """
        Runs the next task.
        Returns True if completed, False otherwise.

        :type  pick_up: bool
        :param pick_up: When True, this method attempts to choose the next
                        task not by searching beginning at the root, but by
                        searching from the position at which the last call
                        of complete_next() left off.
        :type  halt_on_manual: bool
        :param halt_on_manual: When True, this method will not attempt to
                        complete any tasks that have manual=True.
                        See :meth:`SpiffWorkflow.specs.TaskSpec.__init__`
        :rtype:  bool
        :returns: True if all tasks were completed, False otherwise.
        """
        # Try to pick up where we left off.
        blacklist = []
        if pick_up and self.last_task is not None:
            try:
                iter = Task.Iterator(self.last_task, Task.READY)
                task = next(iter)
            except StopIteration:
                task = None
            self.last_task = None
            if task is not None:
                if not (halt_on_manual and task.task_spec.manual):
                    if task.complete():
                        self.last_task = task
                        return True
                blacklist.append(task)

        # Walk through all ready tasks.
        for task in Task.Iterator(self.task_tree, Task.READY):
            for blacklisted_task in blacklist:
                if task._is_descendant_of(blacklisted_task):
                    continue
            if not (halt_on_manual and task.task_spec.manual):
                if task.complete():
                    self.last_task = task
                    return True
            blacklist.append(task)

        # Walk through all waiting tasks.
        for task in Task.Iterator(self.task_tree, Task.WAITING):
            task.task_spec._update(task)
            if not task._has_state(Task.WAITING):
                self.last_task = task
                return True
        return False

    def complete_all(self, pick_up=True, halt_on_manual=True):
        """
        Runs all branches until completion. This is a convenience wrapper
        around :meth:`complete_next`, and the pick_up argument is passed
        along.

        :type  pick_up: bool
        :param pick_up: Passed on to each call of complete_next().
        :type  halt_on_manual: bool
        :param halt_on_manual: When True, this method will not attempt to
                        complete any tasks that have manual=True.
                        See :meth:`SpiffWorkflow.specs.TaskSpec.__init__`
        """
        while self.complete_next(pick_up, halt_on_manual):
            pass

    def get_dump(self):
        """
        Returns a complete dump of the current internal task tree for
        debugging.

        :rtype:  str
        :returns: The debug information.
        """
        return self.task_tree.get_dump()

    def dump(self):
        """
        Like :meth:`get_dump`, but prints the output to the terminal instead
        of returning it.
        """
        print(self.task_tree.dump())

    def serialize(self, serializer, **kwargs):
        """
        Serializes a Workflow instance using the provided serializer.

        :type  serializer: :class:`SpiffWorkflow.serializer.base.Serializer`
        :param serializer: The serializer to use.
        :type  kwargs: dict
        :param kwargs: Passed to the serializer.
        :rtype:  object
        :returns: The serialized workflow.
        """
        return serializer.serialize_workflow(self, **kwargs)

    @classmethod
    def deserialize(cls, serializer, s_state, **kwargs):
        """
        Deserializes a Workflow instance using the provided serializer.

        :type  serializer: :class:`SpiffWorkflow.serializer.base.Serializer`
        :param serializer: The serializer to use.
        :type  s_state: object
        :param s_state: The serialized workflow.
        :type  kwargs: dict
        :param kwargs: Passed to the serializer.
        :rtype:  Workflow
        :returns: The workflow instance.
        """
        return serializer.deserialize_workflow(s_state, **kwargs)
