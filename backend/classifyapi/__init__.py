"""Shared classifier HTTPS API: invite codes, caps, usage, and the handler.

This is a separate, multi-tenant, public-facing concern from the single-user
app. It exposes the existing classifier (agent.classify) over HTTPS so invited
friends can classify their emails using the host's Bedrock credits, without the
API ever storing or logging email content.
"""
