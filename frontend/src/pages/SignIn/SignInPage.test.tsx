import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import { SignInPage } from "./SignInPage";

describe("Sign-in page", () => {
  it("starts Microsoft sign-in only when the user asks", async () => {
    const onSignIn = vi.fn();
    renderWithProviders(<SignInPage onSignIn={onSignIn} />);
    expect(onSignIn).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign in with Microsoft" }));
    expect(onSignIn).toHaveBeenCalledOnce();
  });

  it("shows a sign-in error", () => {
    renderWithProviders(<SignInPage onSignIn={() => {}} error="Sign-in was cancelled. Please try again." />);
    expect(screen.getByRole("alert")).toHaveTextContent("Sign-in was cancelled");
  });
});
