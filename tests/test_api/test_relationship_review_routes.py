"""Relationship route scope, payload and stale decision regressions."""

import pytest

from src.api.auth import create_access_token
from src.models.db import UserModel
from tests.test_services.test_relationship_review import seed


@pytest.mark.asyncio
async def test_routes_reject_sql_and_require_auth(client, async_session):
    db_id, _, _, draft = await seed(async_session)
    await async_session.commit()
    url = f"/api/v1/semantic/{db_id}/relationships"
    assert (await client.get(url)).status_code == 401
    user = await async_session.get(UserModel, 1)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    body = draft.model_dump()
    assert (
        await client.post(url + "/candidates", json={**body, "join_condition": "1=1; DROP TABLE x"}, headers=headers)
    ).status_code == 422
    response = await client.post(url + "/candidates", json=body, headers=headers)
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    listed = await client.get(url + "?search=absent", headers=headers)
    assert listed.json()["items"] == [] and listed.json()["counts"]["pending_relationships"] == 1
    impact = (await client.get(url + f"/{item['id']}/impact?kind=candidate&action=approve", headers=headers)).json()
    decision = {"expected_revision": item["revision"], "impact_token": impact["token"], "acknowledge_impact": True}
    assert (
        await client.post(url + f"/candidates/{item['id']}/approve", json=decision, headers=headers)
    ).status_code == 200
    assert (
        await client.post(url + f"/candidates/{item['id']}/approve", json=decision, headers=headers)
    ).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["anonymous", "nonmember", "wrong_org", "member", "manager", "data_lead", "admin"])
@pytest.mark.parametrize("operation", ["list", "create", "update", "reject", "approve", "disable"])
async def test_rbac_matrix(client, async_session, monkeypatch, role, operation):
    from src.models.db import OrganizationMemberModel, SemanticDatabaseModel
    from src.services.organization_service import ROLE_PERMISSIONS, create_organization
    from src.services.relationship_review_service import (
        decide_relationship,
        preview_relationship_change,
        save_relationship_candidate,
    )

    owner = await async_session.get(UserModel, 1)
    organization = await create_organization(async_session, owner.id, "Review", "relationship-review")
    db_id, _, _, draft = await seed(async_session)
    database = await async_session.get(SemanticDatabaseModel, db_id)
    database.org_id = organization.id
    item = await save_relationship_candidate(async_session, db_id, 1, draft)
    if operation == "disable":
        impact = await preview_relationship_change(async_session, db_id, item.id, kind="candidate", action="approve")
        item = await decide_relationship(
            async_session,
            db_id,
            1,
            item.id,
            kind="candidate",
            action="approve",
            expected_revision=item.revision,
            impact_token=impact.token,
            acknowledge_impact=True,
        )
        item_id, kind = item.active_relationship_id, "active"
    else:
        item_id, kind = item.id, "candidate"
    actor = UserModel(
        id=2, email="actor@example.com", username="actor", full_name="Actor", hashed_password="hash", status="active"
    )
    async_session.add(actor)
    member_role = role if role in ("admin", "data_lead") else "member"
    if role not in ("anonymous", "nonmember"):
        async_session.add(OrganizationMemberModel(org_id=organization.id, user_id=actor.id, role=member_role))
    if role == "manager":
        monkeypatch.setitem(ROLE_PERMISSIONS, "member", {**ROLE_PERMISSIONS["member"], "can_manage_schema": True})
    await async_session.commit()
    headers = (
        {}
        if role == "anonymous"
        else {
            "Authorization": f"Bearer {create_access_token(actor)}",
            "X-Organization-ID": str(organization.id + (1 if role == "wrong_org" else 0)),
        }
    )
    url = f"/api/v1/semantic/{db_id}/relationships"
    body = draft.model_dump()
    body["expected_revision"] = item.revision
    if operation == "list":
        response = await client.get(url, headers=headers)
    elif operation == "create":
        body["relationship_type"] = "one_to_one"
        response = await client.post(url + "/candidates", json=body, headers=headers)
    elif operation == "update":
        response = await client.patch(url + f"/candidates/{item_id}", json=body, headers=headers)
    else:
        decision = {"expected_revision": 1}
        if role == "data_lead" and operation != "reject":
            impact = await preview_relationship_change(async_session, db_id, item_id, kind=kind, action=operation)
            decision.update(impact_token=impact.token, acknowledge_impact=True)
        suffix = f"/{item_id}/disable" if operation == "disable" else f"/candidates/{item_id}/{operation}"
        response = await client.post(url + suffix, json=decision, headers=headers)
    allowed = role == "data_lead" or (role == "manager" and operation in ("list", "create", "update", "reject"))
    expected = 200 if allowed else (401 if role == "anonymous" else 403)
    assert response.status_code == expected, response.text


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_relationship_and_metric(client, async_session, monkeypatch):
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    from src.models.db import CanonicalRelationshipModel, SemanticMetricModel
    from src.models.db_relationships import RelationshipCandidateModel
    from src.services.relationship_review_service import preview_relationship_change, save_relationship_candidate

    db_id, tables, _, draft = await seed(async_session)
    metric = SemanticMetricModel(
        db_id=db_id,
        name="Published",
        description="",
        sql_template="SELECT 1",
        status="approved",
        base_entity_id=tables[0].id,
    )
    async_session.add(metric)
    item = await save_relationship_candidate(async_session, db_id, 1, draft)
    await async_session.commit()
    metric_id, candidate_id = metric.id, item.id
    token = (await preview_relationship_change(async_session, db_id, item.id, kind="candidate", action="approve")).token
    user = await async_session.get(UserModel, 1)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    monkeypatch.setattr(async_session, "commit", AsyncMock(side_effect=RuntimeError("injected database failure")))
    with pytest.raises(RuntimeError, match="injected"):
        await client.post(
            f"/api/v1/semantic/{db_id}/relationships/candidates/{item.id}/approve",
            headers=headers,
            json={"expected_revision": 1, "impact_token": token, "acknowledge_impact": True},
        )
    assert (await async_session.scalars(select(CanonicalRelationshipModel))).all() == []
    assert (await async_session.get(SemanticMetricModel, metric_id)).status == "approved"
    assert (await async_session.get(RelationshipCandidateModel, candidate_id)).status == "pending_review"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"column_pairs": []},
        {"column_pairs": [{"from_column_id": 1}]},
        {"column_pairs": [{"from_column_id": 1, "to_column_id": 2, "sql": "x"}]},
    ],
)
async def test_invalid_pair_shapes_return_422(client, async_session, changes):
    db_id, _, _, draft = await seed(async_session)
    await async_session.commit()
    user = await async_session.get(UserModel, 1)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    response = await client.post(
        f"/api/v1/semantic/{db_id}/relationships/candidates", headers=headers, json={**draft.model_dump(), **changes}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_foreign_candidate_is_hidden(client, async_session):
    from src.services.relationship_review_service import save_relationship_candidate

    db_id, _, _, draft = await seed(async_session)
    foreign_id, _, _, foreign = await seed(async_session)
    item = await save_relationship_candidate(async_session, foreign_id, 1, foreign)
    await async_session.commit()
    user = await async_session.get(UserModel, 1)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    url = f"/api/v1/semantic/{db_id}/relationships"
    assert (
        await client.patch(
            url + f"/candidates/{item.id}", headers=headers, json={**draft.model_dump(), "expected_revision": 1}
        )
    ).status_code == 404
    assert (
        await client.get(url + f"/{item.id}/impact?kind=candidate&action=approve", headers=headers)
    ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pairs",
    [[{"from_column": "customer_id", "to_column": "id"}], [{"from_column_id": 1}], ["malformed"], {"not": "a list"}],
)
async def test_legacy_pair_payload_is_readable_and_can_be_disabled(client, async_session, pairs):
    from src.models.db import CanonicalRelationshipModel

    db_id, tables, _, _ = await seed(async_session)
    active = CanonicalRelationshipModel(
        connection_id=db_id,
        from_entity_id=tables[0].id,
        to_entity_id=tables[1].id,
        relationship_type="many_to_one",
        join_condition="legacy",
        column_pairs=pairs,
        validation_status="needs_review",
        review_status="approved",
    )
    async_session.add(active)
    await async_session.commit()
    active_id = active.id
    user = await async_session.get(UserModel, 1)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    url = f"/api/v1/semantic/{db_id}/relationships"
    listed = await client.get(url, headers=headers)
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["column_pairs"] == pairs and item["errors"][0]["code"] == "INVALID_PAIR"
    impact = (await client.get(url + f"/{active_id}/impact?kind=active&action=disable", headers=headers)).json()
    response = await client.post(
        url + f"/{active_id}/disable",
        headers=headers,
        json={"expected_revision": 1, "impact_token": impact["token"], "acknowledge_impact": True},
    )
    assert response.status_code == 200
    assert response.json()["item"]["column_pairs"] == pairs
    assert (await async_session.get(CanonicalRelationshipModel, active_id)).column_pairs == pairs


@pytest.mark.asyncio
async def test_approved_candidate_patch_preserves_approval_audit(client, async_session):
    from src.models.db_relationships import RelationshipCandidateModel
    from src.services.relationship_review_service import (
        decide_relationship,
        preview_relationship_change,
        save_relationship_candidate,
    )

    db_id, _, _, draft = await seed(async_session)
    item = await save_relationship_candidate(async_session, db_id, 1, draft)
    impact = await preview_relationship_change(async_session, db_id, item.id, kind="candidate", action="approve")
    approved = await decide_relationship(
        async_session,
        db_id,
        1,
        item.id,
        kind="candidate",
        action="approve",
        expected_revision=1,
        impact_token=impact.token,
        acknowledge_impact=True,
    )
    await async_session.commit()
    candidate_id, reviewed_at = approved.id, approved.reviewed_at
    user = await async_session.get(UserModel, 1)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    response = await client.patch(
        f"/api/v1/semantic/{db_id}/relationships/candidates/{candidate_id}",
        headers=headers,
        json={**draft.model_dump(), "expected_revision": approved.revision, "relationship_type": "one_to_one"},
    )
    assert response.status_code == 409
    row = await async_session.get(RelationshipCandidateModel, candidate_id)
    assert row.status == "approved" and row.reviewed_by == 1
    assert row.reviewed_at.replace(tzinfo=None) == reviewed_at.replace(tzinfo=None)
    assert row.revision == approved.revision and row.relationship_type == "many_to_one"
