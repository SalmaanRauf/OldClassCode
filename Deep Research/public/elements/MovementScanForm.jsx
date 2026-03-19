import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import React, { useState } from "react";

export default function MovementScanForm() {
    const data = props || {};
    const [showAdvanced, setShowAdvanced] = useState(Boolean(data.show_advanced));
    const [values, setValues] = useState({
        company_name: data.company_name || "",
        account_id: data.account_id || "",
        industry_override: data.industry_override || "",
        person_name: data.person_name || "",
        geography: data.geography || "",
        notes: data.notes || "",
    });

    const industryOptions = Array.isArray(data.industry_options) ? data.industry_options : [];

    const handleChange = (field, value) => {
        setValues((current) => ({ ...current, [field]: value }));
    };

    const handleSubmit = (event) => {
        event.preventDefault();
        if (typeof submitElement === "function") {
            submitElement({
                ...values,
                show_advanced: showAdvanced,
            });
        }
    };

    const handleCancel = () => {
        if (typeof cancelElement === "function") {
            cancelElement();
        }
    };

    return (
        <Card className="w-full max-w-3xl border-[#dccfbf] bg-white/95 shadow-[0_18px_55px_rgba(48,36,18,0.08)]">
            <form onSubmit={handleSubmit}>
                <CardHeader className="space-y-3">
                    <div className="space-y-1">
                        <p className="text-[0.68rem] font-semibold uppercase tracking-[0.28em] text-[#6f5a42]">
                            Movement scan
                        </p>
                        <CardTitle className="font-serif text-2xl tracking-[-0.04em] text-slate-950">
                            {data.title || "Build a People Movement Brief"}
                        </CardTitle>
                    </div>
                    <CardDescription className="max-w-2xl text-sm leading-6 text-slate-600">
                        {data.description || "Scan an account for executive and buyer movement, then enrich leverage."}
                    </CardDescription>
                    <p className="text-sm leading-6 text-slate-500">{data.scan_hint || ""}</p>
                </CardHeader>

                <CardContent className="grid gap-4 sm:grid-cols-2">
                    <div className="flex flex-col gap-2 sm:col-span-2">
                        <Label htmlFor="company_name">Company / Account</Label>
                        <Input
                            id="company_name"
                            placeholder="Capital One"
                            value={values.company_name}
                            onChange={(event) => handleChange("company_name", event.target.value)}
                            aria-describedby="movement-scan-hint"
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <Label htmlFor="account_id">Account ID</Label>
                        <Input
                            id="account_id"
                            placeholder="Optional account reference"
                            value={values.account_id}
                            onChange={(event) => handleChange("account_id", event.target.value)}
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <Label htmlFor="industry_override">Industry Override</Label>
                        <Select
                            value={values.industry_override || "__infer__"}
                            onValueChange={(value) => handleChange("industry_override", value === "__infer__" ? "" : value)}
                        >
                            <SelectTrigger id="industry_override">
                                <SelectValue placeholder="Infer from account context" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="__infer__">Infer from account context</SelectItem>
                                {industryOptions.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="sm:col-span-2 rounded-[20px] border border-[#e7dccb] bg-[#fcfaf7] px-4 py-4">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                            <div>
                                <p className="text-sm font-medium text-slate-900">Advanced options</p>
                                <p className="mt-1 text-sm leading-6 text-slate-600">
                                    Use these only when the target account needs a named-person path or extra context.
                                </p>
                            </div>
                            <Button
                                type="button"
                                variant="outline"
                                onClick={() => setShowAdvanced((current) => !current)}
                                aria-expanded={showAdvanced}
                                aria-controls="movement-scan-advanced"
                                className="min-h-11"
                            >
                                {showAdvanced ? "Hide" : "Show"}
                            </Button>
                        </div>
                    </div>

                    {showAdvanced ? (
                        <div
                            id="movement-scan-advanced"
                            className="grid gap-4 sm:col-span-2 sm:grid-cols-2"
                        >
                            <div className="flex flex-col gap-2">
                                <Label htmlFor="person_name">Named Person</Label>
                                <Input
                                    id="person_name"
                                    placeholder="Jennifer Brady"
                                    value={values.person_name}
                                    onChange={(event) => handleChange("person_name", event.target.value)}
                                />
                            </div>

                            <div className="flex flex-col gap-2">
                                <Label htmlFor="geography">Geography</Label>
                                <Input
                                    id="geography"
                                    placeholder="United States"
                                    value={values.geography}
                                    onChange={(event) => handleChange("geography", event.target.value)}
                                />
                            </div>

                            <div className="flex flex-col gap-2 sm:col-span-2">
                                <Label htmlFor="notes">Notes</Label>
                                <Textarea
                                    id="notes"
                                    placeholder="Optional context, timing, or focus areas."
                                    rows={3}
                                    value={values.notes}
                                    onChange={(event) => handleChange("notes", event.target.value)}
                                />
                            </div>
                        </div>
                    ) : null}

                    <p id="movement-scan-hint" className="sr-only">
                        {data.scan_hint || "Use the company or account as the primary search anchor."}
                    </p>
                </CardContent>

                <CardFooter className="flex flex-col gap-3 border-t border-[#ece1d2] bg-[#fcfaf7] px-6 py-4 sm:flex-row sm:justify-end">
                    <Button type="button" variant="outline" onClick={handleCancel} className="min-h-11">
                        {data.secondary_cta_label || "Cancel"}
                    </Button>
                    <Button type="submit" className="min-h-11">
                        {data.primary_cta_label || "Run Movement Scan"}
                    </Button>
                </CardFooter>
            </form>
        </Card>
    );
}
