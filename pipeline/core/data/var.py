# -*- coding: utf-8 -*-
"""
Tencent is pleased to support the open source community by making 蓝鲸智云PaaS平台社区版 (BlueKing PaaS Community Edition) available.
Copyright (C) 2017-2019 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at
http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
""" # noqa
from abc import abstractmethod
from django.db.utils import ProgrammingError

from pipeline import exceptions
from pipeline.core.data import library
from pipeline.core.data.context import OutputRef
from pipeline.core.data.expression import ConstantTemplate, format_constant_key
from pipeline.models import VariableModel


class Variable(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value

    @abstractmethod
    def get(self):
        pass


class PlainVariable(Variable):
    def __init__(self, name, value):
        super(PlainVariable, self).__init__(name, value)
        self.name = name
        self.value = value

    def get(self):
        return self.value


class SpliceVariable(Variable):

    def __init__(self, name, value, context):
        super(SpliceVariable, self).__init__(name, value)
        self._value = None
        self._build_reference(context)

    def get(self):
        if not self._value:
            self._resolve()
        return self._value

    def _build_reference(self, context):
        keys = ConstantTemplate(self.value).get_reference()
        refs = {}
        for key in keys:
            refs[key] = OutputRef(format_constant_key(key), context)
        self._refs = refs

    def _resolve(self):
        maps = {}
        for key in self._refs:
            try:
                ref_val = self._refs[key].value
                if issubclass(ref_val.__class__, Variable):
                    ref_val = ref_val.get()
            except exceptions.ReferenceNotExistError:
                continue
            maps[key] = ref_val
        val = ConstantTemplate(self.value).resolve_data(maps)

        self._value = val


class LazyVariableMeta(type):
    def __new__(cls, name, bases, attrs):
        super_new = super(LazyVariableMeta, cls).__new__

        # Also ensure initialization is only performed for subclasses of Model
        # (excluding Model class itself).
        parents = [b for b in bases if isinstance(b, LazyVariableMeta)]
        if not parents:
            return super_new(cls, name, bases, attrs)

        # Create the class
        new_class = super_new(cls, name, bases, attrs)

        if not new_class.code:
            raise exceptions.ConstantReferenceException("LazyVariable %s: code can't be empty."
                                                        % new_class.__name__)

        try:
            obj, created = VariableModel.objects.get_or_create(code=new_class.code,
                                                           defaults={
                                                               'status': __debug__,
                                                           })
            if not created and not obj.status:
                obj.status = True
                obj.save()
        except ProgrammingError:
            # first migrate
            pass

        library.VariableLibrary.variables[new_class.code] = new_class

        return new_class


class LazyVariable(SpliceVariable):
    __metaclass__ = LazyVariableMeta

    def __init__(self, name, value, context, pipeline_data):
        super(LazyVariable, self).__init__(name, value, context)
        self.context = context
        self.pipeline_data = pipeline_data

    # variable reference resolve
    def get(self):
        self.value = super(LazyVariable, self).get()
        return self.get_value()

    # get real value by user code
    @abstractmethod
    def get_value(self):
        pass