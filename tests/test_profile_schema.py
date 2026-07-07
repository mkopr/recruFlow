import pytest
from app.schemas.profile import Profile
from pydantic import ValidationError


def test_profile_accepts_valid_payload_with_all_fields() -> None:
    profile = Profile(
        skills=[{"name": "Python", "category": "language"}],
        past_roles=[
            {
                "title": "Backend Engineer",
                "company": "Acme",
                "start_date": "2019",
                "end_date": "present",
                "description": "Built things",
            }
        ],
        education=[
            {
                "institution": "AGH",
                "degree": "MSc",
                "field_of_study": "Computer Science",
                "start_date": "2014",
                "end_date": "2019",
            }
        ],
        certifications=[{"name": "AWS SAA", "issuer": "AWS", "year": 2022}],
        languages=[{"name": "English"}],
        projects=[
            {
                "name": "EV Charging System",
                "description": "Built a charging network platform",
                "tech_stack": ["Python", "Kubernetes"],
                "client": "Nidec",
                "team_size": 5,
            }
        ],
        industry_tags=["automotive", "wind energy"],
        headline="Software Developer",
        summary="8 years of backend and test-automation experience",
        email="marcin@example.com",
        phone="+48 123 456 789",
        location="Warsaw, Poland",
        links=["https://github.com/example", "https://linkedin.com/in/example"],
        deal_breakers=["no on-call"],
        contract_type_preference="B2B",
        salary_min=15000,
        salary_target=20000,
        location_preference="Warsaw",
        remote_preference=True,
    )

    dumped = profile.model_dump()
    assert dumped["skills"][0]["name"] == "Python"
    assert dumped["skills"][0]["category"] == "language"
    assert dumped["past_roles"][0]["title"] == "Backend Engineer"
    assert dumped["past_roles"][0]["company"] == "Acme"
    assert dumped["education"][0]["institution"] == "AGH"
    assert dumped["certifications"][0]["name"] == "AWS SAA"
    assert dumped["languages"][0]["name"] == "English"
    assert dumped["projects"][0]["name"] == "EV Charging System"
    assert dumped["projects"][0]["tech_stack"] == ["Python", "Kubernetes"]
    assert dumped["projects"][0]["client"] == "Nidec"
    assert dumped["projects"][0]["team_size"] == 5
    assert dumped["industry_tags"] == ["automotive", "wind energy"]
    assert dumped["headline"] == "Software Developer"
    assert dumped["summary"] == "8 years of backend and test-automation experience"
    assert dumped["email"] == "marcin@example.com"
    assert dumped["phone"] == "+48 123 456 789"
    assert dumped["location"] == "Warsaw, Poland"
    assert dumped["links"] == ["https://github.com/example", "https://linkedin.com/in/example"]
    assert dumped["deal_breakers"] == ["no on-call"]
    assert dumped["contract_type_preference"] == "B2B"
    assert dumped["salary_min"] == 15000
    assert dumped["salary_target"] == 20000
    assert dumped["location_preference"] == "Warsaw"
    assert dumped["remote_preference"] is True


def test_profile_accepts_minimal_payload_and_applies_defaults() -> None:
    profile = Profile()

    assert profile.skills == []
    assert profile.past_roles == []
    assert profile.education == []
    assert profile.certifications == []
    assert profile.languages == []
    assert profile.projects == []
    assert profile.industry_tags == []
    assert profile.headline is None
    assert profile.summary is None
    assert profile.email is None
    assert profile.phone is None
    assert profile.location is None
    assert profile.links == []
    assert profile.deal_breakers == []
    assert profile.contract_type_preference is None
    assert profile.salary_min is None
    assert profile.salary_target is None
    assert profile.location_preference is None
    assert profile.remote_preference is None


def test_profile_rejects_skill_missing_name() -> None:
    with pytest.raises(ValidationError):
        Profile(skills=[{"category": "backend"}])


def test_profile_rejects_past_role_missing_company() -> None:
    with pytest.raises(ValidationError):
        Profile(past_roles=[{"title": "Eng"}])


def test_profile_rejects_project_missing_name() -> None:
    with pytest.raises(ValidationError):
        Profile(projects=[{"description": "no name given"}])


def test_profile_accepts_project_with_only_name() -> None:
    profile = Profile(projects=[{"name": "BPY-Assistant"}])

    assert profile.projects[0].name == "BPY-Assistant"
    assert profile.projects[0].tech_stack == []
    assert profile.projects[0].client is None
    assert profile.projects[0].team_size is None


def test_profile_rejects_salary_target_below_salary_min() -> None:
    with pytest.raises(ValidationError, match="salary_target must not be less than salary_min"):
        Profile(salary_min=20000, salary_target=10000)


def test_profile_accepts_salary_target_equal_to_salary_min() -> None:
    profile = Profile(salary_min=15000, salary_target=15000)

    assert profile.salary_min == profile.salary_target == 15000


def test_profile_accepts_unusually_large_and_unusual_skill_set() -> None:
    skills = [{"name": f"made-up-skill-{i}"} for i in range(50)]
    past_roles = [
        {"title": f"Role {i}", "company": f"Company {i}", "description": "unusual role"}
        for i in range(30)
    ]
    languages = [{"name": f"Conlang-{i}"} for i in range(20)]

    profile = Profile(skills=skills, past_roles=past_roles, languages=languages)

    assert len(profile.skills) == 50
    assert len(profile.past_roles) == 30
    assert len(profile.languages) == 20
