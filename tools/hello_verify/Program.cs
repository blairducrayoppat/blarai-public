// BlarAI Windows-Hello approval helper (Vikunja #649, follow-on to #639).
//
// A tiny console front-end over the WinRT
// Windows.Security.Credentials.UI.UserConsentVerifier. It is spawned as a
// subprocess by the Python BiometricApprovalVerifier
// (shared/security/hello_verifier.py) to obtain an operator approve/deny for a
// Policy-Agent ESCALATE verdict via Windows Hello (fingerprint / PIN / face).
//
// The PROCESS EXIT CODE is the contract — stdout is human/diagnostic only and the
// Python side keys off the exit code, never the text. Exit 0 is the ONLY "yes":
//   --check mode      : 0 iff Hello is Available to verify; distinct non-zero per
//                       unavailable state (see CheckExit). Non-interactive — it
//                       raises no dialog, so it is safe to run at launcher startup.
//   verify mode (def) : 0 iff the operator was Verified by Hello; distinct non-zero
//                       per Canceled / RetriesExhausted / DeviceNotPresent / etc.
//                       (see VerifyExit). This raises the SYSTEM Hello dialog.
//
// SAFETY: the verify message is the SAFE one-line action descriptor the caller
// passes (rule label + action summary — labels/descriptors only, never a secret;
// the Python EscalationContext guarantees this). It is shown ONLY in the system
// Hello dialog and is never logged, echoed to stdout, or persisted here.
//
// FAIL-CLOSED: any unexpected exception maps to a non-zero exit (UnexpectedError),
// so the Python side — which treats every non-zero/timeout/missing result as DENY
// — fails closed. There is no code path where an error yields exit 0.

using System;
using System.Threading.Tasks;
using Windows.Security.Credentials.UI;

namespace BlarAI.HelloVerify;

/// <summary>Exit codes for <c>--check</c> (availability probe). 0 == Available.</summary>
internal enum CheckExit
{
    Available = 0,          // UserConsentVerifierAvailability.Available
    DeviceNotPresent = 10,  // no biometric/PIN verifier hardware enrolled
    NotConfiguredForUser = 11,
    DisabledByPolicy = 12,
    DeviceBusy = 13,
    UnknownState = 19,      // a future/unmapped availability enum value
    BadInvocation = 20,     // (unused in --check; reserved, mirrors VerifyExit)
    UnexpectedError = 30,   // any exception — fail-closed
}

/// <summary>Exit codes for verify mode. 0 == Verified.</summary>
internal enum VerifyExit
{
    Verified = 0,           // UserConsentVerificationResult.Verified
    DeviceNotPresent = 10,
    NotConfiguredForUser = 11,
    DisabledByPolicy = 12,
    DeviceBusy = 13,
    RetriesExhausted = 14,
    Canceled = 15,          // operator dismissed / cancelled the Hello prompt
    UnknownResult = 19,     // a future/unmapped result enum value
    BadInvocation = 20,     // no/empty message argument supplied
    UnexpectedError = 30,   // any exception — fail-closed
}

internal static class Program
{
    private static async Task<int> Main(string[] args)
    {
        try
        {
            if (args.Length > 0 &&
                string.Equals(args[0], "--check", StringComparison.OrdinalIgnoreCase))
            {
                return (int)await RunCheckAsync().ConfigureAwait(false);
            }

            return (int)await RunVerifyAsync(args).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            // Fail-closed: any unexpected failure is a non-zero exit. Print the
            // exception TYPE only (not the message, which could in theory echo an
            // argument) to stderr for diagnostics; the Python side reads the code.
            Console.Error.WriteLine($"hello_verify: unexpected error ({ex.GetType().Name})");
            return (int)VerifyExit.UnexpectedError;
        }
    }

    /// <summary>
    /// Non-interactive availability probe. Maps
    /// <see cref="UserConsentVerifierAvailability"/> to a <see cref="CheckExit"/>.
    /// Raises no dialog — safe to run at startup for verifier selection.
    /// </summary>
    private static async Task<CheckExit> RunCheckAsync()
    {
        UserConsentVerifierAvailability availability =
            await UserConsentVerifier.CheckAvailabilityAsync();

        CheckExit code = availability switch
        {
            UserConsentVerifierAvailability.Available => CheckExit.Available,
            UserConsentVerifierAvailability.DeviceNotPresent => CheckExit.DeviceNotPresent,
            UserConsentVerifierAvailability.NotConfiguredForUser => CheckExit.NotConfiguredForUser,
            UserConsentVerifierAvailability.DisabledByPolicy => CheckExit.DisabledByPolicy,
            UserConsentVerifierAvailability.DeviceBusy => CheckExit.DeviceBusy,
            _ => CheckExit.UnknownState,
        };

        // stdout is diagnostic only; the exit code is the contract.
        Console.Out.WriteLine($"availability={availability} exit={(int)code}");
        return code;
    }

    /// <summary>
    /// Interactive verify. Raises the system Hello dialog with the SAFE message and
    /// maps <see cref="UserConsentVerificationResult"/> to a <see cref="VerifyExit"/>.
    /// </summary>
    private static async Task<VerifyExit> RunVerifyAsync(string[] args)
    {
        // The message is the single positional arg (the caller passes the SAFE
        // descriptor). Refuse with a distinct non-zero code if it is absent/blank
        // rather than prompting with an empty/placeholder message — fail-closed and
        // unambiguous for the caller.
        string message = args.Length > 0 ? args[0] : string.Empty;
        if (string.IsNullOrWhiteSpace(message))
        {
            Console.Error.WriteLine("hello_verify: no verification message supplied");
            return VerifyExit.BadInvocation;
        }

        UserConsentVerificationResult result =
            await UserConsentVerifier.RequestVerificationAsync(message);

        VerifyExit code = result switch
        {
            UserConsentVerificationResult.Verified => VerifyExit.Verified,
            UserConsentVerificationResult.DeviceNotPresent => VerifyExit.DeviceNotPresent,
            UserConsentVerificationResult.NotConfiguredForUser => VerifyExit.NotConfiguredForUser,
            UserConsentVerificationResult.DisabledByPolicy => VerifyExit.DisabledByPolicy,
            UserConsentVerificationResult.DeviceBusy => VerifyExit.DeviceBusy,
            UserConsentVerificationResult.RetriesExhausted => VerifyExit.RetriesExhausted,
            UserConsentVerificationResult.Canceled => VerifyExit.Canceled,
            _ => VerifyExit.UnknownResult,
        };

        Console.Out.WriteLine($"result={result} exit={(int)code}");
        return code;
    }
}
