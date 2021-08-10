from __future__ import annotations

import logging
from abc import abstractmethod
from asyncio import Event, create_task, gather, get_event_loop
from contextlib import contextmanager
from typing import Dict, Iterable, List, Optional, Set, Type, TypeVar

from tribler_core.config.tribler_config import TriblerConfig
from tribler_core.notifier import Notifier


class SessionError(Exception):
    pass


class ComponentError(Exception):
    pass


class Session:
    def __init__(self, config: TriblerConfig = None, components: List[Component] = (),
                 shutdown_event: Event = None, notifier: Notifier = None):
        self.config: TriblerConfig = config or TriblerConfig()
        self.shutdown_event: Event = shutdown_event or Event()
        self.notifier: Notifier = notifier or Notifier()
        self.components: Dict[Type[Component], Component] = {}
        for implementation in components:
            self.register(implementation.interface, implementation)

    def register(self, comp_cls: Type[Component], comp: Component):
        if comp.session is not None:
            raise ComponentError(f'Component {comp.__class__.__name__} is already registered in session {comp.session}')
        if comp_cls in self.components:
            raise ComponentError(f'Component class {comp_cls.__name__} is already registered in session {self}')
        self.components[comp_cls] = comp
        comp.session = self

    async def start(self):
        loop = get_event_loop()
        started_events: List[Event] = []
        for comp in self.components.values():
            loop.create_task(comp.start())
            started_events.append(comp.started)
        await gather(*[event.wait() for event in started_events])

    async def shutdown(self):
        await gather(*[create_task(component.stop()) for component in self.components.values()])

    def get(self, interface: Type[T]) -> T:
        imp = self.components.get(interface)
        if imp is None:
            raise ComponentError(f"Component implementation not found for {interface.__name__} in session {self}")
        return imp

    def __enter__(self):
        _session_stack.append(self)

    def __exit__(self, exc_type, exc_val, exc_tb):
        assert _session_stack and _session_stack[-1] is self
        _session_stack.pop()


_default_session: Optional[Session] = None


def _get_default_session() -> Session:
    if _default_session is None:
        raise SessionError("Default session was not set")
    return _default_session


def set_default_session(session: Session):
    global _default_session
    _default_session = session


_session_stack = []


def get_session() -> Session:
    if _session_stack:
        return _session_stack[-1]
    return _get_default_session()


T = TypeVar('T', bound='Component')


class Component:
    enable_in_gui_test_mode = False
    enabled = True

    def __init__(self, interface: Type[Component]):
        assert isinstance(self, interface)
        self.interface = interface
        self.logger = logging.getLogger(interface.__name__)
        self.logger.info('__init__')
        self.session: Optional[Session] = None
        self.components_used_by_me: Set[Component] = set()
        self.in_use_by: Set[Component] = set()
        self.started = Event()
        self.unused = Event()
        # Every component starts unused, so it does not lock the whole system on shutdown
        self.unused.set()

    @classmethod
    def should_be_enabled(cls, config: TriblerConfig):  # pylint: disable=unused-argument
        return False

    @classmethod
    @abstractmethod
    def make_implementation(cls: Type[T], config, enable) -> T:
        assert False, f"Abstract classmethod make_implementation not implemented in class {cls.__name__}"

    @classmethod
    def _find_implementation(cls: Type[T]) -> T:
        session = get_session()
        return session.get(cls)

    @classmethod
    def imp(cls: Type[T]) -> T:
        return cls._find_implementation()

    async def start(self):
        await self.run()
        self.started.set()

    async def stop(self):
        self.logger.info("Waiting for other components to release me")
        await self.unused.wait()
        self.logger.info("Component free, shutting down")
        await self.shutdown()
        await gather(*[self._release_imp(imp) for imp in list(self.components_used_by_me)])

    async def run(self):
        pass

    async def shutdown(self):
        pass

    async def use(self, dependency: Type[T]) -> T:
        dep = dependency.imp()

        self.components_used_by_me.add(dep)
        await dep.started.wait()
        dep.in_use_by.add(self)
        return dep

    async def _release_imp(self, dep: Component):
        assert dep in self.components_used_by_me
        self.components_used_by_me.discard(dep)
        dep.in_use_by.discard(self)
        if not dep.in_use_by:
            dep.unused.set()

    async def release(self, dependency: Type[T]):
        dep = dependency.imp()
        await self._release_imp(dep)


def testcomponent(component_cls):
    component_cls.enabled = False
    return component_cls
