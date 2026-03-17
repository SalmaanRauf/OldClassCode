import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import React, { useState } from "react";

export default function TransitionForm() {
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [values, setValues] = useState({
        person_name: props.person_name || "",
        from_company: props.from_company || "",
        to_company: props.to_company || "",
        new_role: props.new_role || "",
        synthetic_scenario: props.synthetic_scenario ?? true,
        department_hint: props.department_hint || "",
        geography: props.geography || "",
        industry_override: props.industry_override || "",
        additional_context: props.additional_context || "",
    });

    const industryOptions = props.industry_options || [];

    const handleChange = (id, value) => {
        setValues((current) => ({ ...current, [id]: value }));
    };

    return (
        <Card className="w-full max-w-2xl mt-4">
            <CardHeader>
                <CardTitle>Build a Transition Playbook</CardTitle>
                <CardDescription>
                    Validate the move, generate a research plan, and surface warm paths.
                </CardDescription>
            </CardHeader>

            <CardContent className="grid grid-cols-2 gap-4">
                <div className="flex flex-col gap-2">
                    <Label htmlFor="person_name">Person</Label>
                    <Input
                        id="person_name"
                        placeholder="Jennifer Brady"
                        value={values.person_name}
                        onChange={(e) => handleChange("person_name", e.target.value)}
                    />
                </div>

                <div className="flex flex-col gap-2">
                    <Label htmlFor="new_role">New Role</Label>
                    <Input
                        id="new_role"
                        placeholder="Chief Information Officer"
                        value={values.new_role}
                        onChange={(e) => handleChange("new_role", e.target.value)}
                    />
                </div>

                <div className="flex flex-col gap-2">
                    <Label htmlFor="from_company">From Company</Label>
                    <Input
                        id="from_company"
                        placeholder="Capital One"
                        value={values.from_company}
                        onChange={(e) => handleChange("from_company", e.target.value)}
                    />
                </div>

                <div className="flex flex-col gap-2">
                    <Label htmlFor="to_company">To Company</Label>
                    <Input
                        id="to_company"
                        placeholder="Fannie Mae"
                        value={values.to_company}
                        onChange={(e) => handleChange("to_company", e.target.value)}
                    />
                </div>

                <div className="col-span-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                    <label className="flex items-center gap-3 text-sm font-medium text-slate-800">
                        <input
                            type="checkbox"
                            checked={Boolean(values.synthetic_scenario)}
                            onChange={(e) => handleChange("synthetic_scenario", e.target.checked)}
                        />
                        Synthetic scenario
                    </label>
                    <p className="mt-2 text-sm text-slate-600">
                        Keep this on for demo or hypothetical move scenarios.
                    </p>
                </div>

                <div className="col-span-2">
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => setShowAdvanced((current) => !current)}
                    >
                        {showAdvanced ? "Hide Advanced Options" : "Advanced Options"}
                    </Button>
                </div>

                {showAdvanced && (
                    <>
                        <div className="flex flex-col gap-2">
                            <Label htmlFor="department_hint">Department Hint</Label>
                            <Input
                                id="department_hint"
                                placeholder="C-Suite"
                                value={values.department_hint}
                                onChange={(e) => handleChange("department_hint", e.target.value)}
                            />
                        </div>

                        <div className="flex flex-col gap-2">
                            <Label htmlFor="geography">Geography</Label>
                            <Input
                                id="geography"
                                placeholder="United States"
                                value={values.geography}
                                onChange={(e) => handleChange("geography", e.target.value)}
                            />
                        </div>

                        <div className="flex flex-col gap-2 col-span-2">
                            <Label htmlFor="industry_override">Industry Override</Label>
                            <Select
                                value={values.industry_override || "__none__"}
                                onValueChange={(value) =>
                                    handleChange("industry_override", value === "__none__" ? "" : value)
                                }
                            >
                                <SelectTrigger id="industry_override">
                                    <SelectValue placeholder="Infer from company context" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="__none__">Infer from company context</SelectItem>
                                    {industryOptions.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        <div className="flex flex-col gap-2 col-span-2">
                            <Label htmlFor="additional_context">Additional Context</Label>
                            <Textarea
                                id="additional_context"
                                placeholder="Optional context, urgency, or focus areas..."
                                rows={3}
                                value={values.additional_context}
                                onChange={(e) => handleChange("additional_context", e.target.value)}
                            />
                        </div>
                    </>
                )}
            </CardContent>

            <CardFooter className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => cancelElement()}>
                    Cancel
                </Button>
                <Button onClick={() => submitElement(values)}>
                    Build Research Plan
                </Button>
            </CardFooter>
        </Card>
    );
}
