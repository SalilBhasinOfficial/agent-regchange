# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Re-export the ADK App lazily — building it requires GCP credentials
# (vertexai + Gemini), which the Stage-1 offline chain and the unit/
# integration tests deliberately avoid. ``adk run`` and the agents-cli
# playground reach into this package and ask for ``app``; that triggers
# the lazy construction in ``app.agent`` (PEP 562 ``__getattr__``).

__all__ = ["app", "root_agent"]


def __getattr__(name: str):
    if name in __all__:
        from . import agent as _agent
        return getattr(_agent, name)
    raise AttributeError(name)
