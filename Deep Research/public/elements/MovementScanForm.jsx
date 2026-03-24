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
        person_name: data.person_name || "",
        from_company: data.from_company || "",
        to_company: data.to_company || "",
        new_role: data.new_role || "",
        lookback_days: data.lookback_days || 180,
        synthetic_scenario: data.synthetic_scenario ?? true,
        industry_override: data.industry_override || "",
        geography: data.geography || "",
        additional_context: data.additional_context || "",
    });

    const industryOptions = Array.isArray(data.industry_options) ? data.industry_options : [];

    const handleChange = (field, value) => {
        setValues((current) => ({ ...current, [field]: value }));
    };

    const handleSubmit = () => {
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
        <form
            onSubmit={(event) => {
                event.preventDefault();
                handleSubmit();
            }}
        >
        <Card className="w-full max-w-3xl border-[#dccfbf] bg-white/95 shadow-[0_18px_55px_rgba(48,36,18,0.08)]">
                <CardHeader className="space-y-3">
                    <div className="space-y-1">
                        <p className="text-[0.68rem] font-semibold uppercase tracking-[0.28em] text-[#6f5a42]">
                            People movement
                        </p>
                        <CardTitle className="font-serif text-2xl tracking-[-0.04em] text-slate-950">
                            {data.title || "Build a People Movement Brief"}
                        </CardTitle>
                    </div>
                    <CardDescription className="max-w-2xl text-sm leading-6 text-slate-600">
                        {data.description || "Validate the move, generate a research plan, and surface broader people movement."}
                    </CardDescription>
                    <p className="text-sm leading-6 text-slate-500">{data.scan_hint || ""}</p>
                </CardHeader>

                <CardContent className="grid gap-4 sm:grid-cols-2">
                    <div className="flex flex-col gap-2">
                        <Label htmlFor="person_name">Person</Label>
                        <Input
                            id="person_name"
                            placeholder="Jennifer Brady"
                            required
                            value={values.person_name}
                            onChange={(event) => handleChange("person_name", event.target.value)}
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <Label htmlFor="new_role">New Role</Label>
                        <Input
                            id="new_role"
                            placeholder="Chief Information Officer"
                            required
                            value={values.new_role}
                            onChange={(event) => handleChange("new_role", event.target.value)}
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <Label htmlFor="from_company">From Company</Label>
                        <Input
                            id="from_company"
                            placeholder="Capital One"
                            required
                            value={values.from_company}
                            onChange={(event) => handleChange("from_company", event.target.value)}
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <Label htmlFor="to_company">To Company</Label>
                        <Input
                            id="to_company"
                            placeholder="Fannie Mae"
                            required
                            value={values.to_company}
                            onChange={(event) => handleChange("to_company", event.target.value)}
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <Label htmlFor="lookback_days">Lookback Days</Label>
                        <Input
                            id="lookback_days"
                            type="number"
                            min="30"
                            max="365"
                            step="1"
                            required
                            value={values.lookback_days}
                            onChange={(event) => handleChange("lookback_days", event.target.value)}
                        />
                    </div>

                    <div className="rounded-[20px] border border-[#e7dccb] bg-[#fcfaf7] px-4 py-4">
                        <div className="flex items-center gap-3">
                            <input
                                id="synthetic_scenario"
                                type="checkbox"
                                checked={Boolean(values.synthetic_scenario)}
                                onChange={(event) => handleChange("synthetic_scenario", event.target.checked)}
                            />
                            <Label htmlFor="synthetic_scenario" className="mb-0 cursor-pointer">
                                Synthetic scenario
                            </Label>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-slate-600">
                            Keep this on for demo or hypothetical move scenarios.
                        </p>
                    </div>

                    <div className="sm:col-span-2 rounded-[20px] border border-[#e7dccb] bg-[#fcfaf7] px-4 py-4">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                            <div>
                                <p className="text-sm font-medium text-slate-900">Advanced options</p>
                                <p className="mt-1 text-sm leading-6 text-slate-600">
                                    Override industry inference or add context that should shape the research plan.
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
                        <div id="movement-scan-advanced" className="grid gap-4 sm:col-span-2 sm:grid-cols-2">
                            <div className="flex flex-col gap-2">
                                <Label htmlFor="geography">Geography</Label>
                                <Input
                                    id="geography"
                                    placeholder="United States"
                                    value={values.geography}
                                    onChange={(event) => handleChange("geography", event.target.value)}
                                />
                            </div>

                            <div className="flex flex-col gap-2">
                                <Label htmlFor="industry_override">Industry Override</Label>
                                <Select
                                    value={values.industry_override || "__infer__"}
                                    onValueChange={(value) => handleChange("industry_override", value === "__infer__" ? "" : value)}
                                >
                                    <SelectTrigger id="industry_override">
                                        <SelectValue placeholder="Financial Services" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="__infer__">Financial Services (default)</SelectItem>
                                        {industryOptions.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>

                            <div className="flex flex-col gap-2 sm:col-span-2">
                                <Label htmlFor="additional_context">Additional Context</Label>
                                <Textarea
                                    id="additional_context"
                                    placeholder="Optional context, urgency, or focus areas."
                                    rows={3}
                                    value={values.additional_context}
                                    onChange={(event) => handleChange("additional_context", event.target.value)}
                                />
                            </div>
                        </div>
                    ) : null}
                </CardContent>

                <CardFooter className="flex flex-col gap-3 border-t border-[#ece1d2] bg-[#fcfaf7] px-6 py-4 sm:flex-row sm:justify-end">
                    <Button type="button" variant="outline" onClick={handleCancel} className="min-h-11">
                        {data.secondary_cta_label || "Cancel"}
                    </Button>
                    <Button type="submit" className="min-h-11">
                        {data.primary_cta_label || "Generate Research Plan"}
                    </Button>
                </CardFooter>
        </Card>
        </form>
    );
}
