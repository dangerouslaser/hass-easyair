"""Config flow for Bosch EasyAir (SingleKey ID browser login)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EasyAirApi, EasyAirAuthError, EasyAirError, exchange_code, new_login, token_claims
from .const import CONF_TOKENS, DOMAIN

CONF_REDIRECT_URL = "redirect_url"
SCHEMA = vol.Schema({vol.Required(CONF_REDIRECT_URL): str})


class EasyAirConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._login: dict[str, str] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._login_step("user", user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._login_step("reauth_confirm", user_input)

    async def _login_step(self, step_id: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if self._login is None:
            self._login = new_login()

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                tokens = await exchange_code(
                    session, user_input[CONF_REDIRECT_URL], self._login["verifier"]
                )
                await EasyAirApi(session, tokens).device_list()
            except EasyAirAuthError:
                errors["base"] = "invalid_auth"
            except EasyAirError:
                errors["base"] = "cannot_connect"
            else:
                claims = token_claims(tokens["id_token"])
                await self.async_set_unique_id(claims["sub"])
                if self.source == "reauth":
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates={CONF_TOKENS: tokens}
                    )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=claims.get("email") or "Bosch EasyAir",
                    data={CONF_TOKENS: tokens},
                )
            # Authorization codes are single-use: issue a fresh login link.
            self._login = new_login()

        return self.async_show_form(
            step_id=step_id,
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"login_url": self._login["url"]},
        )
