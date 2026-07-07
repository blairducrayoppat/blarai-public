"""BlarAI UI Backend — named-pipe JSON-RPC bridge (ADR-014).

Hosts the existing :class:`TransportGateway` + :class:`SessionStore` behind a
Windows named pipe so a separate-process front end (the WinUI 3 app) can drive
the Python services without any TCP/IP listening socket. See ADR-014 for the
bridge decision and ADR-009 for the interaction surface it supersedes.
"""
