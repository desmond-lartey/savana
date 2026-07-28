# Classification API Reference

This page documents the **land-system classification** API, the top-level
`savana.*` modules. For precipitation product assessment, see the separate
[Precipitation Assessment API Reference](api_rainfall.md), which documents
the `savana.rainfall.*` modules.

!!! note "Same names, different modules"
    A few module names appear in **both** packages: `config`, `thresholds`,
    and `viz`. On this page they always mean the classification versions
    (`savana.config`, `savana.thresholds`, `savana.viz`). Their rainfall
    namesakes (`savana.rainfall.config`, etc.) are entirely separate and
    documented on the rainfall API page.

## High-level entry point

::: savana.pipeline
    options:
        show_root_heading: true

## Feature engineering

::: savana.composites
    options:
        show_root_heading: true

::: savana.indices
    options:
        show_root_heading: true

::: savana.rue
    options:
        show_root_heading: true

::: savana.thresholds
    options:
        show_root_heading: true

::: savana.masks
    options:
        show_root_heading: true

## Training and classification

::: savana.sampling
    options:
        show_root_heading: true

::: savana.classifiers
    options:
        show_root_heading: true

::: savana.change
    options:
        show_root_heading: true

## Accuracy and export

::: savana.accuracy
    options:
        show_root_heading: true

::: savana.exports
    options:
        show_root_heading: true

## Insights and visualisation

::: savana.insights
    options:
        show_root_heading: true

::: savana.viz
    options:
        show_root_heading: true

::: savana.viz_geolibre
    options:
        show_root_heading: true

## Natural-language agent

::: savana.agents
    options:
        show_root_heading: true

## Configuration and Earth Engine

::: savana.config
    options:
        show_root_heading: true

::: savana.ee_init
    options:
        show_root_heading: true
