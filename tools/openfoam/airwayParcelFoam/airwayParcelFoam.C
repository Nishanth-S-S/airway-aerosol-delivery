/*---------------------------------------------------------------------------*\
Application
    airwayParcelFoam   (airway-aerosol-delivery project, OpenFOAM v2406)

Description
    One-way-coupled transport of a kinematic particle cloud through a
    PRE-COMPUTED, TIME-VARYING airflow.

    Based on icoUncoupledKinematicParcelFoam (which freezes U). Here, at every
    cloud time step the air velocity is linearly interpolated in time between
    the two stored snapshots of an airflow case (constant/airwayParcelDict:
    airflowCase) that bracket the current time. The airflow is therefore never
    re-solved: each of the 9 airflow solutions is reused by its 16 particle
    cases. Particles do not feed back on the air (one-way coupling).

    Extra bookkeeping written to postProcessing/airwayParcels/:
      massBudget.csv            per step: injected, suspended, deposited,
                                escaped (per boundary), first-crossed mass
      targetPlaneCrossings.csv  FIRST crossing of each parcel through the
                                target-entry disc (plane, normal, radius)
      escapes.csv               each parcel leaving the domain (boundary, time)
      finalParcels.csv          every parcel left at the end (deposited =
                                active 0 with wall position; suspended = 1)
      tracks.csv                positions of a sample of parcels (trajectories)
      injections.csv            release time, true mass and position of every parcel (v2)

    Injection flux weighting (optional, inletFluxWeighting parabolic): the
    stock patch injection places parcels uniformly over the inlet AREA. For a
    parabolic inlet profile the aerosol FLUX is proportional to the local
    velocity, so the number of particles carried by each new parcel is scaled
    by 2(1 - r^2/R^2) (mean 1 over the inlet area; no renormalisation).

    Serial only (parcel ids are used as unique keys).
\*---------------------------------------------------------------------------*/

#include "fvCFD.H"
#include "basicKinematicCloud.H"
#include "OFstream.H"
#include "Map.H"
#include "HashSet.H"
#include "mathematicalConstants.H"

using namespace Foam::constant::mathematical;

int main(int argc, char *argv[])
{
    argList::addNote("One-way particle transport in a stored, time-varying airflow");
    argList::noParallel();
    argList::addOption("cloud", "name", "cloud name (default kinematicCloud)");

    #include "setRootCaseLists.H"
    #include "createTime.H"
    #include "createMesh.H"
    #include "readGravitationalAcceleration.H"

    // ------------------------------------------------------------- settings
    IOdictionary airwayDict
    (
        IOobject("airwayParcelDict", runTime.constant(), mesh,
                 IOobject::MUST_READ, IOobject::NO_WRITE)
    );
    const fileName airflowCase(airwayDict.get<fileName>("airflowCase").expand());
    const scalar rhoAir(airwayDict.get<scalar>("rhoAir"));
    const scalar nuAir(airwayDict.get<scalar>("nuAir"));
    const scalar rhoTrue(airwayDict.get<scalar>("particleDensityTrue"));
    const vector planePoint(airwayDict.get<vector>("targetPlanePoint"));
    const vector planeNormal(normalised(airwayDict.get<vector>("targetPlaneNormal")));
    const scalar planeRadius(airwayDict.get<scalar>("targetPlaneRadius"));
    const vector inletCentre(airwayDict.get<vector>("inletCentre"));
    const vector inletNormal(normalised(airwayDict.get<vector>("inletNormal")));
    const scalar inletRadius(airwayDict.get<scalar>("inletRadius"));
    const word fluxWeighting(airwayDict.getOrDefault<word>("inletFluxWeighting", "none"));
    const label trackEvery(airwayDict.getOrDefault<label>("trackSampleEvery", 50));
    const label trackStride(airwayDict.getOrDefault<label>("trackStepStride", 5));
    const List<Tuple2<word, vector>> outletCentres
    (
        airwayDict.get<List<Tuple2<word, vector>>>("exitCentres")
    );

    // ------------------------------------------------------------- airflow source
    Info<< "Airflow source case: " << airflowCase << nl;
    Time airTime
    (
        Time::controlDictName, airflowCase.path(), airflowCase.name(),
        false, false
    );
    instantList airTimes(airTime.times());
    {
        DynamicList<instant> keep;
        for (const instant& t : airTimes)
        {
            if (t.name() != "constant" && isFile(airflowCase/t.name()/"U")) keep.append(t);
        }
        airTimes = keep;
    }
    if (airTimes.size() < 2)
    {
        FatalErrorInFunction << "Need >= 2 stored U snapshots in " << airflowCase
            << exit(FatalError);
    }
    Info<< "  " << airTimes.size() << " snapshots, t = " << airTimes.first().value()
        << " .. " << airTimes.last().value() << nl;

    airTime.setTime(airTimes.first(), 0);
    fvMesh airMesh
    (
        IOobject(fvMesh::defaultRegion, airTime.timeName(), airTime, IOobject::MUST_READ)
    );
    if (airMesh.nCells() != mesh.nCells())
    {
        FatalErrorInFunction << "Airflow mesh (" << airMesh.nCells()
            << " cells) differs from particle mesh (" << mesh.nCells() << ")"
            << exit(FatalError);
    }

    auto loadU = [&](label i)
    {
        airTime.setTime(airTimes[i], i);
        return autoPtr<volVectorField>::New
        (
            IOobject("U", airTime.timeName(), airMesh, IOobject::MUST_READ, IOobject::NO_WRITE),
            airMesh
        );
    };

    // ------------------------------------------------------------- fields
    volVectorField U
    (
        IOobject("U", runTime.timeName(), mesh, IOobject::NO_READ, IOobject::AUTO_WRITE),
        mesh, dimensionedVector(dimVelocity, Zero), "calculated"
    );
    surfaceScalarField phi
    (
        IOobject("phi", runTime.timeName(), mesh, IOobject::NO_READ, IOobject::NO_WRITE),
        fvc::flux(U)
    );
    volScalarField rho
    (
        IOobject("rho", runTime.timeName(), mesh, IOobject::NO_READ, IOobject::NO_WRITE),
        mesh, dimensionedScalar(dimDensity, rhoAir)
    );
    volScalarField mu
    (
        IOobject("mu", runTime.timeName(), mesh, IOobject::NO_READ, IOobject::NO_WRITE),
        mesh, dimensionedScalar(dimDensity*dimViscosity, rhoAir*nuAir)
    );

    label ia = -1;
    autoPtr<volVectorField> Ua, Ub;
    auto setAirflow = [&](scalar t)
    {
        label i = 0;
        while (i < airTimes.size() - 2 && airTimes[i + 1].value() <= t) ++i;
        if (i != ia)
        {
            Ua = loadU(i);
            Ub = loadU(i + 1);
            ia = i;
        }
        const scalar ta = airTimes[i].value(), tb = airTimes[i + 1].value();
        const scalar w = min(max((t - ta)/(tb - ta), 0.0), 1.0);
        U.primitiveFieldRef() = (1 - w)*Ua().primitiveField() + w*Ub().primitiveField();
        forAll(U.boundaryField(), pi)
        {
            U.boundaryFieldRef()[pi] ==
                (1 - w)*Ua().boundaryField()[pi] + w*Ub().boundaryField()[pi];
        }
        phi = fvc::flux(U);
    };
    setAirflow(runTime.value());

    const word cloudName(args.getOrDefault<word>("cloud", "kinematicCloud"));
    basicKinematicCloud cloud(cloudName, rho, U, mu, g);
    const label seed(airwayDict.getOrDefault<label>("randomSeed", 1));
    cloud.rndGen().reset(seed);
    Info<< "Random seed " << seed << nl;

    // ------------------------------------------------------------- bookkeeping
    const fileName outDir(runTime.path()/"postProcessing"/"airwayParcels");
    mkDir(outDir);
    OFstream budget(outDir/"massBudget.csv");
    OFstream crossings(outDir/"targetPlaneCrossings.csv");
    OFstream escapes(outDir/"escapes.csv");
    OFstream tracks(outDir/"tracks.csv");
    OFstream injections(outDir/"injections.csv");
    injections << "origId,time,mass,d,nParticle,x,y,z,weight" << nl;
    budget << "time,injected_mass,suspended_mass,deposited_mass,escaped_mass";
    for (const auto& oc : outletCentres) budget << ",escaped_" << oc.first();
    budget << ",crossed_mass,n_injected,n_active,n_deposited" << nl;
    crossings << "time,origId,d,nParticle,mass,x,y,z" << nl;
    escapes << "time,origId,boundary,d,nParticle,mass,x,y,z" << nl;
    tracks << "time,origId,x,y,z,active" << nl;

    auto trueMass = [&](const basicKinematicCloud::parcelType& p)
    {
        return p.nParticle()*rhoTrue*pi/6.0*pow3(p.d());
    };

    Map<point> prevPos;                // origId -> position before the step (active)
    Map<scalar> massOf;                // origId -> true mass (fixed after injection)
    Map<scalar> dOf, nOf;
    labelHashSet crossed;
    scalar injectedMass = 0, crossedMass = 0;
    HashTable<scalar> escapedMass;
    for (const auto& oc : outletCentres) escapedMass.set(oc.first(), 0);
    label step = 0;

    Info<< "\nStarting time loop\n" << endl;
    while (runTime.loop())
    {
        const scalar dt = runTime.deltaTValue();
        const scalar t1 = runTime.value();
        const scalar t0 = t1 - dt;
        setAirflow(0.5*(t0 + t1));

        prevPos.clear();
        for (const auto& p : cloud)
        {
            if (p.active()) prevPos.set(p.origId(), p.position());
        }

        cloud.evolve();
        ++step;

        // ---- newly injected parcels: flux weighting + record their mass
        DynamicList<basicKinematicCloud::parcelType*> fresh;
        for (auto& p : cloud)
        {
            if (!massOf.found(p.origId())) fresh.append(&p);
        }
        if (fresh.size())
        {
            scalarField w(fresh.size(), 1.0);
            if (fluxWeighting == "parabolic")
            {
                forAll(fresh, k)
                {
                    vector r = fresh[k]->position() - inletCentre;
                    r -= (r & inletNormal)*inletNormal;
                    w[k] = max(0.0, 2.0*(1.0 - magSqr(r)/sqr(inletRadius)));
                }
            }
            // Importance weight w = 2(1 - r^2/R^2) has mean exactly 1 over area-uniform positions,
            // so the expected injected mass is unchanged. (v1 renormalised per time step; with only a
            // few parcels per step that partly cancelled the weighting -> continuous and pulsed runs
            // were weighted differently. Fixed in v2: no per-step renormalisation.)
            const scalar scale = 1.0;
            forAll(fresh, k)
            {
                auto& p = *fresh[k];
                p.nParticle() *= w[k]*scale;
                massOf.set(p.origId(), trueMass(p));
                // release time = end of step minus the parcel's age; position after its first sub-step
                injections << p.origId() << ',' << t1 - p.age() << ',' << trueMass(p) << ',' << p.d()
                    << ',' << p.nParticle() << ',' << p.position().x() << ',' << p.position().y()
                    << ',' << p.position().z() << ',' << w[k] << nl;
                dOf.set(p.origId(), p.d());
                nOf.set(p.origId(), p.nParticle());
                injectedMass += trueMass(p);
            }
        }

        // ---- first crossings of the target-entry disc + census
        labelHashSet present;
        scalar suspended = 0, deposited = 0;
        label nActive = 0, nDep = 0;
        for (const auto& p : cloud)
        {
            const label id = p.origId();
            present.insert(id);
            const scalar m = massOf[id];
            if (p.active()) { suspended += m; ++nActive; }
            else            { deposited += m; ++nDep; }

            if (!crossed.found(id))
            {
                const auto it = prevPos.cfind(id);
                if (it.good())
                {
                    const point& x0 = it.val();
                    const point& x1 = p.position();
                    const scalar d0 = (x0 - planePoint) & planeNormal;
                    const scalar d1 = (x1 - planePoint) & planeNormal;
                    if (d0 < 0 && d1 >= 0)
                    {
                        const scalar f = d0/(d0 - d1);
                        const point xc = x0 + f*(x1 - x0);
                        vector r = xc - planePoint;
                        r -= (r & planeNormal)*planeNormal;
                        if (mag(r) <= planeRadius)
                        {
                            crossed.insert(id);
                            crossedMass += m;
                            crossings << t0 + f*dt << ',' << id << ',' << p.d() << ','
                                << p.nParticle() << ',' << m << ',' << xc.x() << ','
                                << xc.y() << ',' << xc.z() << nl;
                        }
                    }
                }
            }
            if (trackEvery > 0 && id % trackEvery == 0 && step % trackStride == 0 && p.active())
            {
                tracks << t1 << ',' << id << ',' << p.position().x() << ','
                    << p.position().y() << ',' << p.position().z() << ',' << 1 << nl;
            }
        }

        // ---- parcels that left the domain this step
        forAllConstIters(prevPos, it)
        {
            const label id = it.key();
            if (present.found(id)) continue;
            const point& x0 = it.val();
            word best("unknown");
            scalar bestD = GREAT;
            for (const auto& oc : outletCentres)
            {
                const scalar dd = mag(x0 - oc.second());
                if (dd < bestD) { bestD = dd; best = oc.first(); }
            }
            escapedMass[best] += massOf[id];
            escapes << t1 << ',' << id << ',' << best << ',' << dOf[id] << ','
                << nOf[id] << ',' << massOf[id] << ',' << x0.x() << ',' << x0.y()
                << ',' << x0.z() << nl;
        }

        scalar escapedTotal = 0;
        forAllConstIters(escapedMass, it) escapedTotal += it.val();
        budget << t1 << ',' << injectedMass << ',' << suspended << ',' << deposited
            << ',' << escapedTotal;
        for (const auto& oc : outletCentres) budget << ',' << escapedMass[oc.first()];
        budget << ',' << crossedMass << ',' << massOf.size() << ',' << nActive << ','
            << nDep << nl;

        runTime.write();
        if (step % 50 == 0)
        {
            Info<< "Time = " << runTime.timeName() << "  parcels " << massOf.size()
                << "  active " << nActive << "  deposited " << nDep
                << "  injected mass " << injectedMass << nl;
            runTime.printExecutionTime(Info);
        }
    }

    // ------------------------------------------------------------- final census
    OFstream fin(outDir/"finalParcels.csv");
    fin << "origId,active,d,nParticle,mass,x,y,z" << nl;
    for (const auto& p : cloud)
    {
        fin << p.origId() << ',' << (p.active() ? 1 : 0) << ',' << p.d() << ','
            << p.nParticle() << ',' << massOf[p.origId()] << ',' << p.position().x()
            << ',' << p.position().y() << ',' << p.position().z() << nl;
    }
    Info<< "End\n" << endl;
    return 0;
}
