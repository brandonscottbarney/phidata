import collections.abc
import inspect

from os import getenv
from uuid import uuid4
from types import GeneratorType
from typing import Any, Optional, Callable, Dict

from pydantic import BaseModel, Field, ConfigDict, field_validator, PrivateAttr

from phi.run.response import RunResponse, RunEvent  # noqa: F401
from phi.memory.workflow import WorkflowMemory, WorkflowRun
from phi.storage.workflow import WorkflowStorage
from phi.utils.log import logger, set_log_level_to_debug, set_log_level_to_info
from phi.utils.merge_dict import merge_dictionaries
from phi.workflow.session import WorkflowSession


class Workflow(BaseModel):
    # -*- Workflow settings
    # Workflow name
    name: Optional[str] = None
    # Workflow description
    description: str
    # Workflow UUID (autogenerated if not set)
    workflow_id: Optional[str] = Field(None, validate_default=True)
    # Metadata associated with this workflow
    workflow_data: Optional[Dict[str, Any]] = None

    # -*- User settings
    # ID of the user interacting with this workflow
    user_id: Optional[str] = None
    # Metadata associated with the user interacting with this workflow
    user_data: Optional[Dict[str, Any]] = None

    # -*- Session settings
    # Session UUID (autogenerated if not set)
    session_id: Optional[str] = Field(None, validate_default=True)
    # Session name
    session_name: Optional[str] = None
    # Metadata associated with this session
    session_data: Optional[Dict[str, Any]] = None
    # Session state stored in the database
    session_state: Dict[str, Any] = Field(default_factory=dict)

    # -*- Workflow Memory
    memory: WorkflowMemory = WorkflowMemory()

    # -*- Workflow Storage
    storage: Optional[WorkflowStorage] = None
    # WorkflowSession from the database: DO NOT SET MANUALLY
    _workflow_session: Optional[WorkflowSession] = None

    # debug_mode=True enables debug logs
    debug_mode: bool = Field(False, validate_default=True)
    # monitoring=True logs workflow information to phidata.com
    monitoring: bool = getenv("PHI_MONITORING", "false").lower() == "true"
    # telemetry=True logs minimal telemetry for analytics
    # This helps us improve the Agent and provide better support
    telemetry: bool = getenv("PHI_TELEMETRY", "true").lower() == "true"

    # DO NOT SET THE FOLLOWING FIELDS MANUALLY
    # -*- Workflow run details
    # Run ID: do not set manually
    run_id: Optional[str] = None
    # Input to the Workflow run: do not set manually
    run_input: Optional[Dict[str, Any]] = None
    # Response from the Workflow run: do not set manually
    run_response: RunResponse = Field(default_factory=RunResponse)

    # The run function provided by the subclass
    _subclass_run: Callable = PrivateAttr()
    # Parameters of the run function
    _run_parameters: Dict[str, Any] = PrivateAttr()
    # Return type of the run function
    _run_return_type: Optional[str] = PrivateAttr()

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    @field_validator("workflow_id", mode="before")
    def set_workflow_id(cls, v: Optional[str]) -> str:
        workflow_id = v or str(uuid4())
        logger.debug(f"*********** Worfklow ID: {workflow_id} ***********")
        return workflow_id

    @field_validator("session_id", mode="before")
    def set_session_id(cls, v: Optional[str]) -> str:
        session_id = v or str(uuid4())
        logger.debug(f"*********** Worflow Session ID: {session_id} ***********")
        return session_id

    @field_validator("debug_mode", mode="before")
    def set_log_level(cls, v: bool) -> bool:
        if v or getenv("PHI_DEBUG", "false").lower() == "true":
            set_log_level_to_debug()
            logger.debug("Debug logs enabled")
        elif v is False:
            set_log_level_to_info()
        return v

    def get_workflow_data(self) -> Dict[str, Any]:
        workflow_data = self.workflow_data or {}
        if self.name is not None:
            workflow_data["name"] = self.name
        return workflow_data

    def get_session_data(self) -> Dict[str, Any]:
        session_data = self.session_data or {}
        if self.session_name is not None:
            session_data["session_name"] = self.session_name
        return session_data

    def get_workflow_session(self) -> WorkflowSession:
        """Get a WorkflowSession object, which can be saved to the database"""

        return WorkflowSession(
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            user_id=self.user_id,
            memory=self.memory.to_dict(),
            workflow_data=self.get_workflow_data(),
            user_data=self.user_data,
            session_data=self.get_session_data(),
            session_state=self.session_state,
        )

    def from_workflow_session(self, session: WorkflowSession):
        """Load the existing Workflow from a WorkflowSession (from the database)"""

        # Get the session_id, workflow_id and user_id from the database
        if self.session_id is None and session.session_id is not None:
            self.session_id = session.session_id
        if self.workflow_id is None and session.workflow_id is not None:
            self.workflow_id = session.workflow_id
        if self.user_id is None and session.user_id is not None:
            self.user_id = session.user_id

        # Read workflow_data from the database
        if session.workflow_data is not None:
            # Get name from database and update the workflow name if not set
            if self.name is None and "name" in session.workflow_data:
                self.name = session.workflow_data.get("name")

            # If workflow_data is set in the workflow, update the database workflow_data with the workflow's workflow_data
            if self.workflow_data is not None:
                # Updates workflow_session.workflow_data in place
                merge_dictionaries(session.workflow_data, self.workflow_data)
            self.workflow_data = session.workflow_data

        # Read user_data from the database
        if session.user_data is not None:
            # If user_data is set in the workflow, update the database user_data with the workflow's user_data
            if self.user_data is not None:
                # Updates workflow_session.user_data in place
                merge_dictionaries(session.user_data, self.user_data)
            self.user_data = session.user_data

        # Read session_data from the database
        if session.session_data is not None:
            # Get the session_name from database and update the current session_name if not set
            if self.session_name is None and "session_name" in session.session_data:
                self.session_name = session.session_data.get("session_name")

            # If session_data is set in the workflow, update the database session_data with the workflow's session_data
            if self.session_data is not None:
                # Updates workflow_session.session_data in place
                merge_dictionaries(session.session_data, self.session_data)
            self.session_data = session.session_data

        # Read session_state from the database
        if session.session_state is not None:
            # The workflow's session_state takes precedence
            if self.session_state is not None:
                # Updates workflow_session.session_state in place
                merge_dictionaries(session.session_state, self.session_state)
            self.session_state = session.session_state

        # Read memory from the database
        if session.memory is not None:
            try:
                if "runs" in session.memory:
                    self.memory.runs = [WorkflowRun(**m) for m in session.memory["runs"]]
            except Exception as e:
                logger.warning(f"Failed to load WorkflowMemory: {e}")
        logger.debug(f"-*- WorkflowSession loaded: {session.session_id}")

    def read_from_storage(self) -> Optional[WorkflowSession]:
        """Load the WorkflowSession from storage.

        Returns:
            Optional[WorkflowSession]: The loaded WorkflowSession or None if not found.
        """
        if self.storage is not None and self.session_id is not None:
            self._workflow_session = self.storage.read(session_id=self.session_id)
            if self._workflow_session is not None:
                self.from_workflow_session(session=self._workflow_session)
        return self._workflow_session

    def write_to_storage(self) -> Optional[WorkflowSession]:
        """Save the WorkflowSession to storage

        Returns:
            Optional[WorkflowSession]: The saved WorkflowSession or None if not saved.
        """
        if self.storage is not None:
            self._workflow_session = self.storage.upsert(session=self.get_workflow_session())
        return self._workflow_session

    def load_session(self, force: bool = False) -> Optional[str]:
        """Load an existing session from the database and return the session_id.
        If a session does not exist, create a new session.

        - If a session exists in the database, load the session.
        - If a session does not exist in the database, create a new session.
        """
        # If a workflow_session is already loaded, return the session_id from the workflow_session
        # if session_id matches the session_id from the workflow_session
        if self._workflow_session is not None and not force:
            if self.session_id is not None and self._workflow_session.session_id == self.session_id:
                return self._workflow_session.session_id

        # Load an existing session or create a new session
        if self.storage is not None:
            # Load existing session if session_id is provided
            logger.debug(f"Reading WorkflowSession: {self.session_id}")
            self.read_from_storage()

            # Create a new session if it does not exist
            if self._workflow_session is None:
                logger.debug("-*- Creating new WorkflowSession")
                # write_to_storage() will create a new WorkflowSession
                # and populate self._workflow_session with the new session
                self.write_to_storage()
                if self._workflow_session is None:
                    raise Exception("Failed to create new WorkflowSession in storage")
                logger.debug(f"-*- Created WorkflowSession: {self._workflow_session.session_id}")
                self.log_workflow_session()
        return self.session_id

    def run(self, *args: Any, **kwargs: Any):
        logger.error(f"{self.__class__.__name__}.run() method not implemented.")
        return

    def run_workflow(self, *args: Any, **kwargs: Any):
        self.run_id = str(uuid4())
        self.run_input = {"args": args, "kwargs": kwargs}
        self.run_response = RunResponse(run_id=self.run_id, session_id=self.session_id, workflow_id=self.workflow_id)
        self.read_from_storage()

        logger.debug(f"*********** Workflow Run Start: {self.run_id} ***********")
        result = self._subclass_run(*args, **kwargs)

        # The run_workflow() method handles both Iterator[RunResponse] and RunResponse

        # Case 1: The run method returns an Iterator[RunResponse]
        if isinstance(result, (GeneratorType, collections.abc.Iterator)):
            # Initialize the run_response content
            self.run_response.content = ""

            def result_generator():
                for item in result:
                    if isinstance(item, RunResponse):
                        # Update the run_id, session_id and workflow_id of the RunResponse
                        item.run_id = self.run_id
                        item.session_id = self.session_id
                        item.workflow_id = self.workflow_id

                        # Update the run_response with the content from the result
                        if item.content is not None and isinstance(item.content, str):
                            self.run_response.content += item.content
                    else:
                        logger.warning(f"Workflow.run() should only yield RunResponse objects, got: {type(item)}")
                    yield item

                # Add the run to the memory
                self.memory.add_run(WorkflowRun(input=self.run_input, response=self.run_response))
                # Write this run to the database
                self.write_to_storage()
                logger.debug(f"*********** Workflow Run End: {self.run_id} ***********")

            return result_generator()
        # Case 2: The run method returns a RunResponse
        elif isinstance(result, RunResponse):
            # Update the result with the run_id, session_id and workflow_id of the workflow run
            result.run_id = self.run_id
            result.session_id = self.session_id
            result.workflow_id = self.workflow_id

            # Update the run_response with the content from the result
            if result.content is not None and isinstance(result.content, str):
                self.run_response.content = result.content

            # Add the run to the memory
            self.memory.add_run(WorkflowRun(input=self.run_input, response=self.run_response))
            # Write this run to the database
            self.write_to_storage()
            logger.debug(f"*********** Workflow Run End: {self.run_id} ***********")
            return result
        else:
            logger.warning(f"Workflow.run() should only return RunResponse objects, got: {type(result)}")
            return None

    def __init__(self, **data):
        super().__init__(**data)
        self.name = self.name or self.__class__.__name__
        # Check if 'run' is provided by the subclass
        if self.__class__.run is not Workflow.run:
            # Store the original run method bound to the instance
            self._subclass_run = self.__class__.run.__get__(self)
            # Get the parameters of the run method
            sig = inspect.signature(self.__class__.run)
            # Convert parameters to a serializable format
            self._run_parameters = {
                name: {
                    "name": name,
                    "default": param.default if param.default is not inspect.Parameter.empty else None,
                    "annotation": (
                        param.annotation.__name__
                        if hasattr(param.annotation, "__name__")
                        else (
                            str(param.annotation).replace("typing.Optional[", "").replace("]", "")
                            if "typing.Optional" in str(param.annotation)
                            else str(param.annotation)
                        )
                    )
                    if param.annotation is not inspect.Parameter.empty
                    else None,
                    "required": param.default is inspect.Parameter.empty,
                }
                for name, param in sig.parameters.items()
                if name != "self"
            }
            # Determine the return type of the run method
            return_annotation = sig.return_annotation
            self._run_return_type = (
                return_annotation.__name__
                if return_annotation is not inspect.Signature.empty and hasattr(return_annotation, "__name__")
                else str(return_annotation)
                if return_annotation is not inspect.Signature.empty
                else None
            )
            # Replace the instance's run method with run_workflow
            object.__setattr__(self, "run", self.run_workflow.__get__(self))
        else:
            # This will log an error when called
            self._subclass_run = self.run
            self._run_parameters = {}
            self._run_return_type = None

    def log_workflow_session(self):
        logger.debug(f"*********** Logging WorkflowSession: {self.session_id} ***********")

    def rename_session(self, session_id: str, name: str):
        workflow_session = self.storage.read(session_id)
        if workflow_session is None:
            raise Exception(f"WorkflowSession not found: {session_id}")
        workflow_session.session_data["session_name"] = name
        self.storage.upsert(workflow_session)

    def delete_session(self, session_id: str):
        self.storage.delete_session(session_id)
